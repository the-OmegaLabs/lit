from typing import Literal

import requests
from readability import Document
from markdownify import markdownify
import trafilatura

from tavily import TavilyClient
client = TavilyClient(api_key="your-tavily-api-key")

class Plugin:
    def __init__(self):
        self.name = "Web search"
        self.version = 'v1.1'
        self.author = 'Stevesuk0 <stevesukawa@outlook.com>'

        self.export_function = {
            'Grabbing': self.grab_page,
            'Searching': self.web_search
        }

    def grab_page(self, url: str):
        html = requests.get(
            url,
            headers={
                "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 LitSearch/{self.version}"
            }
        ).text

        doc = Document(html)

        content_html = doc.summary()

        markdown = markdownify(
            content_html,
            heading_style="ATX"
        )

        if not markdown.strip(): # fallback
            html = trafilatura.fetch_url(
                url
            )

            markdown = trafilatura.extract(
                html,
                output_format="markdown"
            )

        return {
            "result": markdown
        }

    def web_search(
        self,
        query: str,
        answer: Literal["advanced", "basic", "none"] = "none",
        topic: Literal["general", "news", "finance"] = "general",
        depth: Literal["advanced", "basic", "fast", "ultra-fast"] = "basic",
        max_results: int = 5,
        time_range: Literal["none", "day", "week", "month", "year"] = "none",
        include_images: bool = False,
        include_images_desc: bool = False,
        include_favicon: bool = False,
        include_usage: bool = False,
        include_raw_content: Literal["none", "text", "markdown"] = "none"
    ):
        """
        Tavily web search wrapper.
        """

        if answer == "none":
            include_answer = False
        else:
            include_answer = answer

        if include_raw_content == "none":
            raw_content = False
        else:
            raw_content = include_raw_content

        params = {
            "query": query,
            "include_answer": include_answer,
            "topic": topic,
            "search_depth": depth,
            "max_results": max_results,
            "include_images": include_images,
            "include_image_descriptions": include_images_desc,
            "include_favicon": include_favicon,
            "include_usage": include_usage,
            "include_raw_content": raw_content,
        }

        if time_range != "none":
            params["time_range"] = time_range

        response = client.search(**params)

        return response