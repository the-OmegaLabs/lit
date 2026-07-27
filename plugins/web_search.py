import requests
from readability import Document
from markdownify import markdownify
import trafilatura

class Plugin:
    def __init__(self):
        self.name = "Web search"
        self.version = 'v1.0'
        self.author = 'Stevesuk0 <stevesukawa@outlook.com>'

        self.export_function = {
            'Grabbing': self.grab_page
        }

    def grab_page(self, url: str):
        html = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
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