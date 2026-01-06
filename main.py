import os
import glob
import aiohttp
from io import BytesIO
from PIL import Image, ImageFilter
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp
from porntrex_api import Client
from base_api.base import BaseCore

BASE_VIDEO_URL = "https://www.porntrex.com/video/"
BASE_MODEL_URL = "https://www.porntrex.com/models/"
BASE_CHANNEL_URL = "https://www.porntrex.com/channels/"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

@register("porntrex", "vmoranv", "Porntrex API 插件", "1.0.0")
class PorntrexPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _get_client(self) -> Client:
        proxy = self.config.get("proxy", "")
        if proxy:
            core = BaseCore(proxies={"http": proxy, "https": proxy})
        else:
            core = BaseCore()
        return Client(core=core)

    def _clean_cache(self):
        for f in glob.glob(os.path.join(CACHE_DIR, "*")):
            try:
                os.remove(f)
            except OSError:
                pass

    async def _blur_image(self, url: str) -> str:
        blur = self.config.get("blur_level", 20)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.read()
        img = Image.open(BytesIO(data))
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        path = os.path.join(CACHE_DIR, f"thumb_{hash(url)}.jpg")
        img.save(path, "JPEG")
        return path

    async def _resolve_video_url(self, video_id: str) -> str:
        """通过 video_id 获取完整的视频 URL（包含标题 slug）"""
        import re
        from astrbot.api import logger
        url = f"{BASE_VIDEO_URL}{video_id}/"
        logger.info(f"[porntrex] 请求页面: {url}")
        proxy = self.config.get("proxy", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy if proxy else None) as resp:
                html = await resp.text()
                logger.info(f"[porntrex] 响应状态: {resp.status}, HTML长度: {len(html)}")
                # 从 HTML 中提取 canonical URL
                match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html)
                if match:
                    final_url = match.group(1)
                    logger.info(f"[porntrex] 找到canonical URL: {final_url}")
                    return final_url
                # 尝试 og:url
                match = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', html)
                if match:
                    final_url = match.group(1)
                    logger.info(f"[porntrex] 找到og:url: {final_url}")
                    return final_url
                logger.info(f"[porntrex] 未找到完整URL，使用原始URL")
                return url

    @filter.command("pt_video")
    async def video_info(self, event: AstrMessageEvent, video_url: str):
        """获取视频信息\u200E"""
        from astrbot.api import logger
        self._clean_cache()
        try:
            if not video_url.startswith("http"):
                video_url = await self._resolve_video_url(video_url)
            logger.info(f"[porntrex] 最终请求URL: {video_url}")
            client = self._get_client()
            video = client.get_video(video_url)
            logger.info(f"[porntrex] 视频标题: {video.title}")
            thumb_path = await self._blur_image(video.thumbnail)
            info = (
                f"标题: {video.title}\n"
                f"作者: {video.author}\n"
                f"时长: {video.duration}\n"
                f"观看: {video.views}\n"
                f"发布: {video.publish_date}\n"
                f"分类: {', '.join(video.categories)}\n"
                f"标签: {', '.join(video.tags)}\n"
                f"画质: {', '.join(video.video_qualities())}p\n"
                f"描述: {video.description[:100]}...\u200E"
            )
            yield event.chain_result([Comp.Image.fromFileSystem(thumb_path), Comp.Plain(info)])
        except Exception as e:
            yield event.plain_result(f"获取失败: {e}\u200E")

    @filter.command("pt_model")
    async def model_info(self, event: AstrMessageEvent, model_id: str):
        """获取模特信息\u200E"""
        self._clean_cache()
        try:
            client = self._get_client()
            model = client.get_model(f"{BASE_MODEL_URL}{model_id}/")
            thumb_path = await self._blur_image(model.image)
            info_dict = model.information
            info_str = "\n".join([f"{k}: {v}" for k, v in info_dict.items()])
            info = f"名称: {model.name}\n{info_str}\u200E"
            yield event.chain_result([Comp.Image.fromFileSystem(thumb_path), Comp.Plain(info)])
        except Exception as e:
            yield event.plain_result(f"获取失败: {e}\u200E")

    @filter.command("pt_channel")
    async def channel_info(self, event: AstrMessageEvent, channel_id: str):
        """获取频道信息\u200E"""
        self._clean_cache()
        try:
            client = self._get_client()
            channel = client.get_channel(f"{BASE_CHANNEL_URL}{channel_id}/")
            thumb_path = await self._blur_image(channel.image)
            info_dict = channel.information
            info_str = "\n".join([f"{k}: {v}" for k, v in info_dict.items()])
            info = f"名称: {channel.name}\n{info_str}\u200E"
            yield event.chain_result([Comp.Image.fromFileSystem(thumb_path), Comp.Plain(info)])
        except Exception as e:
            yield event.plain_result(f"获取失败: {e}\u200E")

    @filter.command("pt_search")
    async def search_videos(self, event: AstrMessageEvent, query: str):
        """搜索视频\u200E"""
        self._clean_cache()
        try:
            client = self._get_client()
            results = []
            for i, video in enumerate(client.search(query, pages=1)):
                if i >= 5:
                    break
                results.append(f"{i+1}. {video.title}\n{video.url}\u200E")
            if results:
                yield event.plain_result("\n\n".join(results) + "\u200E")
            else:
                yield event.plain_result("未找到结果\u200E")
        except Exception as e:
            yield event.plain_result(f"搜索失败: {e}\u200E")

    async def terminate(self):
        self._clean_cache()
