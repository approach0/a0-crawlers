import os
import time
import errno
import json
import pycurl
import certifi
from bs4 import BeautifulSoup
from replace_post_tex import replace_dollar_tex
from replace_post_tex import replace_display_tex
from replace_post_tex import replace_inline_tex
from io import BytesIO
from typing import Dict, List, Union
import xml.etree.ElementTree as ET

root_url = "https://kuing.cjhb.site"
file_prefix = "kuing"
sitemap_url = f"{root_url}/sitemap.xml"

vt100_BLUE = "\033[94m"
vt100_WARNING = "\033[93m"
vt100_RESET = "\033[0m"
DIVISIONS = 500

def print_err(err_str: str):
    with open("error.log", "a") as f:
        print(vt100_WARNING)
        f.write(f"[error] {err_str}\n")
        print(err_str)
        print(vt100_RESET)


def curl(url: str, c):
    buf = BytesIO()
    url = url.encode("iso-8859-1")
    c.setopt(c.HTTPHEADER, [f"User-agent: curl/7.77.0"])
    c.setopt(c.URL, url)
    c.setopt(c.WRITEFUNCTION, buf.write)
    retry_cnt = 0
    while True:
        try:
            c.perform()
        except (KeyboardInterrupt, SystemExit):
            print("user aborting...")
            raise
        except Exception as err:
            if retry_cnt < 10:
                retry_cnt += 1
            else:
                buf.close()
                raise
            wait_time = retry_cnt * 10.0
            print(err)
            print(f"[curl] sleep {wait_time} and try again...")
            time.sleep(wait_time)
            continue
        break
    res_str = buf.getvalue()
    buf.close()
    return res_str


def extract_content(soup: BeautifulSoup) -> Dict[str, Union[str, int]]:
    content_data = {
        "forum": soup.title.text.split(" - ")[-2],
        "keywords": soup.find('meta', {'name': 'keywords'})['content'] if soup.find('meta', {'name': 'keywords'}) else "",
        "content": "\n".join([replace_dollar_tex(replace_inline_tex(replace_display_tex(msg.get_text()))) for msg in soup.select("td.t_f")])
    }
    return content_data


def save_json(path: str, content_data: Dict[str, Union[str, int]], url: str):
    data = {
        "url": url,
        "tags": content_data["keywords"].split(",") if content_data["keywords"] else [],
        "text": content_data["content"]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)


def save_preview(path: str, content_data: Dict[str, Union[str, int]], url: str):
    # put preview into HTML template
    script_dir = os.path.dirname(__file__)
    with open(os.path.join(script_dir, "template.html"), "r", encoding="utf-8") as f:
        fmt_str = f.read()
    content_html = content_data["content"].replace("\n", "</br>")
    preview = fmt_str.replace("{PREVIEW}", content_html).replace("{URL}", url)
    # save preview
    with open(path, "w", encoding="utf-8") as f:
        f.write(preview)


def get_curl():
    c = pycurl.Curl()
    c.setopt(c.CONNECTTIMEOUT, 8)
    c.setopt(c.TIMEOUT, 10)
    c.setopt(c.CAINFO, certifi.where())
    c.setopt(c.FOLLOWLOCATION, 1)
    return c


def mkdir_p(path: str):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise Exception("mkdir needs permission")


def get_file_path(url: str) -> str:
    file_id = hash(url) % DIVISIONS
    directory = f"./tmp/{file_id}"
    return os.path.join(directory, file_prefix) + str(file_id)


def process_page(url: str, c: pycurl.Curl):
    try:
        page_content = curl(url, c)
        soup = BeautifulSoup(page_content, "html.parser")
        for pstatus in soup.select("i.pstatus"):
            pstatus.decompose()
        for quote in soup.select("div.quote > blockquote > font[size='2']"):
            quote.decompose()
        content_data = extract_content(soup)
        if content_data["forum"] != "初等数学讨论":
            return
        file_path = get_file_path(url)
        mkdir_p(os.path.dirname(file_path))
        save_json(f"{file_path}.json", content_data, url)
        save_preview(f"{file_path}.html", content_data, url)
    except Exception as err:
        print_err(f"Error processing {url}: {err}")


def crawl_sitemap():
    c = get_curl()
    try:
        sitemap_content = curl(sitemap_url, c)
        sitemap_tree = ET.fromstring(sitemap_content)
        urls = [elem.text for elem in sitemap_tree.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        for url in urls:
            process_page(url, c)
    except Exception as err:
        print_err(f"Error crawling sitemap: {err}")

if __name__ == "__main__":
    crawl_sitemap()