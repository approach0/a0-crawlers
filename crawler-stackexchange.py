#!/usr/bin/python3
import time
import pycurl
import certifi
import os
import errno
import code
import re
import json
import sys
import getopt
import filecmp
import math
from replace_post_tex import replace_dollar_tex
from replace_post_tex import replace_display_tex
from replace_post_tex import replace_inline_tex
from io import BytesIO
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple, Union

SE_SITE_ROOT = {
    "mse": "https://math.stackexchange.com",
    "matheducators": "https://matheducators.stackexchange.com",
    "mof": "https://mathoverflow.net",
    "stats": "https://stats.stackexchange.com",
    "physics": "https://physics.stackexchange.com"
}

# default target StackExchange site
file_prefix = "mse"
root_url = SE_SITE_ROOT[file_prefix]

vt100_BLUE = "\033[94m"
vt100_WARNING = "\033[93m"
vt100_RESET = "\033[0m"
DIVISIONS = 500
PAGESIZE = 30


def print_err(err_str: str):
    with open("error.log", "a") as f:
        print(vt100_WARNING)
        f.write(f"[error] {err_str}\n")
        print(err_str)
        print(vt100_RESET)


def curl(sub_url: str, c):
    buf = BytesIO()
    url = f"{root_url}{sub_url}"
    print(f"[curl] {url}")
    url = url.encode("iso-8859-1")
    c.setopt(c.HTTPHEADER, [f"User-agent: curl/7.77.0"])
    c.setopt(c.URL, url)
    c.setopt(c.WRITEFUNCTION, buf.write)
    #c.setopt(c.VERBOSE, True)
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


def extract_p_tag_text(soup: BeautifulSoup) -> str:
    txt = ""
    p_tags = soup.find_all("p")
    for p in p_tags:
        if p.text != " ":
            txt += f"{p.text}\n"
    return txt


def extract_comments_text(soup: BeautifulSoup) -> str:
    return "".join(
        f"{span.text}\n"
        for div in soup.find_all("div", class_="comments")
        for span in div.find_all("span", class_="comment-copy")
    )


def crawl_post_page(sub_url: str, c: pycurl.Curl) -> Tuple[str, List[str]]:
    try:
        post_page = curl(sub_url, c)
    except:
        raise
    s = BeautifulSoup(post_page, "html.parser")
    # get title
    question_header = s.find(id="question-header")
    if question_header is None:
        raise Exception("question header is None")
    title = str(question_header.h1.string)
    post_txt = f"{title}\n\n"
    # get question
    question = s.find(id="question")
    if question is None:
        raise Exception("No question tag found.")
    post_txt += (
        f"{extract_p_tag_text(question)}\n{extract_comments_text(question)}\n"
    )
    post_txt += extract_p_tag_text(question)
    post_txt += '\n'
    # get question comments
    post_txt += extract_comments_text(question)
    post_txt += '\n'

    # get post tags
    tags = question.find_all("a", class_="post-tag")
    taglist = []
    if tags is not None:
        taglist = [t.string for t in tags]

    # get answers
    answers = s.find(id="answers")
    if answers is None:
        raise Exception("answers tag is None")
    for answer in answers.findAll("div", {"class": "answer"}):
        post_txt += extract_p_tag_text(answer)
        post_txt += '\n'
        # get answer comments
        post_txt += extract_comments_text(answer)
        post_txt += '\n'
    return post_txt, taglist


def mkdir_p(path: str):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise Exception("mkdir needs permission")


def save_preview(path: str, post_txt: str, url: str):
    # put preview into HTML template
    script_dir = os.path.dirname(__file__)
    f = open(os.path.join(script_dir, "template.html"), "r")
    fmt_str = f.read()
    f.close()
    post_txt = post_txt.replace("\n", "</br>")
    preview = fmt_str.replace("{PREVIEW}", post_txt).replace("{URL}", url)
    # save preview
    with open(path, "w", encoding="utf8") as f:
        f.write(preview)


def save_json(path: str, post_txt: str, tags: List[str], url: str):
    with open(path, "w") as f:
        f.write(
            json.dumps(
                {"url": url, "tags": tags, "text": post_txt}, sort_keys=True
            )
        )


def get_curl():
    c = pycurl.Curl()
    c.setopt(c.CONNECTTIMEOUT, 8)
    c.setopt(c.TIMEOUT, 10)
    c.setopt(c.CAINFO, certifi.where())

    # redirect on 3XX error
    c.setopt(c.FOLLOWLOCATION, 1)
    return c


def crawl_total_pages():
    c = get_curl()
    try:
        questions_page = curl('/questions?tab=newest', c)
        s = BeautifulSoup(questions_page, "html.parser")
        pagers = s.find("div", {"class": "pager"}).find_all('a')
        return int(pagers[-2].text)

    except Exception as err:
        print(err, file=sys.stderr)
        return 0

def list_post_links(page: int, sortby, c: pycurl.Curl):
    # sortby can be 'newest', 'active' etc.
    sub_url = f"/questions?pagesize={PAGESIZE}&sort={sortby}&page={page}"

    retry_cnt = 0
    while True:
        try:
            navi_page = curl(sub_url, c)
        except Exception as err:
            yield (None, None, err)
        s = BeautifulSoup(navi_page, "html.parser")
        summary_tags = s.find_all("div", {"class": "question-summary"})

        # if server is showing us our frequency is too much...
        print(f"{len(summary_tags)} questions in this page")
        if len(summary_tags) == 0:
            if retry_cnt < 60:
                retry_cnt += 1
            wait_time = retry_cnt * 10.0
            print(f"Request too frequent? Wait {wait_time} sec ...")
            time.sleep(wait_time)
        else:
            break

    for div in summary_tags:
        a_tag = div.find("a", {"class": "question-hyperlink"})
        if a_tag is None:
            continue
        elif not div.has_attr("id") or not a_tag.has_attr("href"):
            continue
        yield (div["id"], a_tag["href"], None)


def get_file_path(post_id: int) -> str:
    directory = f"./tmp/{post_id % DIVISIONS}"
    return os.path.join(directory, file_prefix) + str(post_id)


def process_post(
    post_id: int,
    post_txt: str,
    taglist: List[str],
    url: str,
    if_save_preview: bool,
):
    # decide sub-directory
    file_path = get_file_path(post_id)
    try:
        mkdir_p(os.path.dirname(file_path))
    except:
        raise
    # process TeX mode pieces
    post_txt = replace_display_tex(post_txt)
    post_txt = replace_inline_tex(post_txt)
    post_txt = replace_dollar_tex(post_txt)

    # do not touch time stamp if previously
    # an identical file already exists.
    jsonfile = f"{file_path}.json"
    if os.path.isfile(jsonfile):
        print(f"[exists]{jsonfile}")
        save_json(f"{file_prefix}.tmp", post_txt, taglist, url)
        if filecmp.cmp(f"{file_prefix}.tmp", jsonfile):
            # two files are identical, do not touch
            print("[identical, no touch]")
            return
        else:
            print("[overwrite]")

    # two files are different, save files
    save_json(jsonfile, post_txt, taglist, url)
    if if_save_preview:
        save_preview(f"{file_path}.html", post_txt, url)


def crawl_pages(
    sortby, start: int, end: int, extra_opt: Dict[str, Union[bool, str]]
):
    c = get_curl()
    for page in range(start, end + 1):
        print(vt100_BLUE)
        print(f"page#{page} in [{start}, {end}]  order by {sortby}")
        print(vt100_RESET)
        succ_posts = 0
        for div_id, sub_url, err in list_post_links(page, sortby, c):
            if err is not None:
                print_err(f"page {page}")
                break
            res = re.search("question-summary-(\d+)", div_id)
            if not res:
                print_err(f"div ID {div_id}")
                continue
            ID = int(res.group(1))
            file_path = get_file_path(ID)
            if os.path.isfile(file_path + ".json"):
                if not extra_opt["overwrite"]:
                    print("[exists, skip]", file_path)
                    # count on success
                    succ_posts += 1
                    continue
            try:
                sub_url = f"{sub_url}?noredirect=1"
                url = f"{root_url}{sub_url}"
                post_txt, taglist = crawl_post_page(sub_url, get_curl())
                process_post(
                    ID, post_txt, taglist, url, extra_opt["save-preview"]
                )
            except (KeyboardInterrupt, SystemExit):
                print("[abort]")
                return "abort"
            except Exception as err:
                print_err(f"post {url}: {err}")
                continue

            # count on success
            succ_posts += 1

            # sleep to avoid request too frequently.
            time.sleep(1.5)

        # log crawled page number
        with open(f"{file_prefix}.log", "a") as page_log:
            page_log.write(f"page {page}: {succ_posts} posts successful.\n")
    return "finish"


def help(arg0: str):
    print(
        "DESCRIPTION: crawler script for StackExchange"
        "\n\n"
        "SYNOPSIS:\n"
        f"{arg0} "
        f"[--site {' | '.join([k for k in SE_SITE_ROOT.keys()])} ] "
        "[-b | --begin-page <page>] "
        "[-e | --end-page <page>] "
        "[-c | --crawler <crawler-number>/<total-crawlers>] "
        "[--total-pages] "
        "[--no-overwrite] "
        "[--patrol] "
        "[--save-preview] "
        "[--hook-script <script name>] "
        "[-p | --post <post id>] "
        "\n"
    )
    sys.exit(1)


def main(args: List[str]):
    argv = args[1:]
    try:
        opts, _ = getopt.getopt(
            argv,
            "s:b:e:p:c:h",
            [
                "site=",
                "begin-page=",
                "end-page=",
                "crawler=",
                "total-pages",
                "post=",
                "no-overwrite",
                "patrol",
                "save-preview",
                "hook-script=",
            ],
        )
    except:
        help(args[0])

    # default arguments
    global file_prefix
    global root_url
    extra_opt = {
        "overwrite": True,
        "hookscript": "",
        "patrol": False,
        "save-preview": False,
    }
    begin_page = 1
    end_page = -1

    for opt, arg in opts:
        if opt in ("-b", "--begin-page"):
            begin_page = int(arg)
            continue
        elif opt in ("-e", "--end-page"):
            end_page = int(arg)
            continue
        elif opt in ("-c", "--crawler"):
            crawler, total_crawlers = map(lambda x: int(x), arg.split('/'))
            total_pages = crawl_total_pages()
            pages_per_crawler = math.ceil(total_pages / total_crawlers)
            begin_page = 1 + (crawler - 1) * pages_per_crawler
            end_page = crawler * pages_per_crawler
            continue
        elif opt in ("--total-pages"):
            total_pages = crawl_total_pages()
            print('Total pages:', total_pages)
            quit(0)
        elif opt in ("-p", "--post"):
            sub_url = "/questions/" + arg
            sub_url = sub_url + "?noredirect=1"
            full_url = root_url + sub_url
            post_txt, taglist = crawl_post_page(sub_url, get_curl())
            process_post(int(arg), post_txt, taglist, full_url, True)
            exit(0)
        elif opt in ("--no-overwrite"):
            extra_opt["overwrite"] = False
        elif opt in ("--patrol"):
            extra_opt["patrol"] = True
        elif opt in ("--save-preview"):
            extra_opt["save-preview"] = True
        elif opt in ("--hook-script"):
            extra_opt["hookscript"] = arg
        elif opt in ("--site"):
            file_prefix = arg
            root_url = SE_SITE_ROOT[arg]
        else:
            help(args[0])

    if end_page >= begin_page:
        while True:
            # crawling newest pages
            r = crawl_pages("newest", begin_page, end_page, extra_opt)
            if r == "abort":
                break

            # if patrol mode is enabled, also crawl recently active
            # posts.
            if extra_opt["patrol"]:
                # crawling recently active pages
                r = crawl_pages("active", begin_page, end_page, extra_opt)
                if r == "abort":
                    break

            # now it is the time to invoke hookscript.
            if extra_opt["hookscript"]:
                os.system(extra_opt["hookscript"])

            if extra_opt["patrol"]:
                # if patrol mode is enabled, loop forever.
                pass
            else:
                break
    else:
        help(args[0])


if __name__ == "__main__":
    main(sys.argv)
