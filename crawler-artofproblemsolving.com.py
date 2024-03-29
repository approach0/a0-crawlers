#!/usr/bin/python3
import time
import pycurl
import certifi
import os
import errno
import json
import sys
import getopt
import filecmp
import html
from urllib.parse import urlencode
from replace_post_tex import replace_dollar_tex
from replace_post_tex import replace_display_tex
from replace_post_tex import replace_inline_tex
from slimit import ast
from slimit.parser import Parser
from io import BytesIO
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

root_url = "https://artofproblemsolving.com"
file_prefix = "aops"

vt100_BLUE = "\033[94m"
vt100_WARNING = "\033[93m"
vt100_RESET = "\033[0m"
DIVISIONS = 500

# load parser globally for sharing, it is painfully slow
slimit_parser = Parser()


def print_err(err_str: str):
    with open("error.log", "a") as f:
        print(vt100_WARNING)
        err_str = f"[error] {err_str}\n"
        f.write(err_str)
        print(err_str)
        print(vt100_RESET)


def curl(sub_url: str, c, post=None):
    ua = UserAgent()
    buf = BytesIO()
    print(f"[curl] {sub_url}")
    url = f"{root_url}{sub_url}"
    url = url.encode("iso-8859-1")
    c.setopt(c.HTTPHEADER, [f"User-agent: {ua.random}"])
    c.setopt(c.URL, url)
    c.setopt(c.WRITEFUNCTION, buf.write)
    c.setopt(c.FOLLOWLOCATION, True)
    # c.setopt(c.VERBOSE, True)
    if post is not None:
        c.setopt(c.POST, 1)
        c.setopt(c.POSTFIELDS, urlencode(post))
    errs = 0
    while True:
        try:
            c.perform()
        except (KeyboardInterrupt, SystemExit):
            print("user aborting...")
            raise
        except Exception:
            errs = errs + 1
            if errs > 3:
                buf.close()
                raise
            print("[curl] try again...")
            continue
        break
    res_str = buf.getvalue()
    buf.close()
    return res_str


def parse_op_name(obj):
    if isinstance(obj, ast.DotAccessor):
        if isinstance(obj.node, ast.Identifier):
            l = f"{obj.node.value}.{obj.identifier.value}"
        else:
            l = f"{parse_op_name(obj.node)}.{obj.identifier.value}"
    elif isinstance(obj, ast.String):
        l = obj.value
        # no using strip here, because it can remove more than 1
        # instance of quotes, which is not desired and can cause issues
        if l.startswith('"') and l.endswith('"'):
            l = l[1:-1]
        l = l.encode().decode("unicode_escape")
    elif hasattr(obj, "value"):
        l = obj.value
    else:
        l = "<UnknownName>"
    return l


# In AoPS post_canonical field, some weird LaTeX macro are used,
# we need to replace them to commonly used LaTeX symbols.
def convert_canonical_tex(s: str) -> str:
    return (
        s.replace("\\minus{}", "-")
        .replace("\\plus{}", "+")
        .replace("\\equal{}", "=")
        .replace("\\/", "/")
    )


def parse_node(node):
    ret = {}
    if hasattr(node, "value") or isinstance(node, ast.DotAccessor):
        return parse_op_name(node)
    if isinstance(node, ast.Object):
        for prop in node.properties:
            l = parse_op_name(prop.left)
            r = parse_node(prop.right)
            ret[l] = r
        return ret
    elif isinstance(node, ast.Array):
        list = []
        for child in node:
            list.append(parse_node(child))
        return list
    elif isinstance(node, ast.FunctionCall):
        return "<FunctionCall>"
    elif isinstance(node, ast.FuncExpr):
        return "<FuncExpr>"
    elif isinstance(node, ast.Program):
        for child in node:
            if isinstance(child, ast.ExprStatement):
                expr = child.expr
                if isinstance(expr, ast.Assign):
                    l = parse_op_name(expr.left)

                    ret[l] = parse_node(expr.right)
    else:
        return "<UnknownRight>"
    return ret


def get_aops_data(page):
    s = BeautifulSoup(page, "html.parser")
    parser = slimit_parser
    for script in s.findAll("script"):
        if "AoPS.bootstrap_data" in script.string:
            try:
                tree = parser.parse(script.string)
                parsed = parse_node(tree)
                return parsed
            except SyntaxError:
                return None

    return None


def crawl_topic_page(sub_url, category_id, topic_id, c, extra_opt):
    try:
        topic_page = curl(sub_url, c)
    except Exception:
        raise

    parsed = get_aops_data(topic_page)
    topic_data = parsed["AoPS.bootstrap_data"]["preload_cmty_data"]["topic_data"]
    session_data = parsed["AoPS.session"]

    # get title
    title = html.unescape(topic_data["topic_title"])

    num_posts = int(topic_data["num_posts"])
    posts_data_tmp = topic_data["posts_data"]
    posts_data = []

    # now this is a bit tricky, but if there are more posts
    # than we received, AoPS sens first 15 and last 15 posts,
    # remove all posts that should be shown only from the end
    for post in posts_data_tmp:
        if post["show_from_start"] == "true":
            posts_data.append(post)

    fetched_posts = 0
    while fetched_posts < num_posts and (len(posts_data) > 0):
        post_number = posts_data[0]["post_number"]
        post_id = posts_data[0]["post_id"]
        # compose title
        topic_txt = title
        if post_number != "1":
            topic_txt += f" (posts after #{post_number})"
        topic_txt += "\n\n"
        # get posts
        for post in posts_data:
            topic_txt += f"{post['post_canonical']}\n\n"
        # save posts
        post_url = f"/community/c{category_id}h{topic_id}p{post_id}"
        full_url = root_url + post_url
        file_path = get_file_path(category_id, topic_id, post_id)
        process_topic(file_path, topic_txt, full_url, extra_opt)

        # keep track of where we are
        fetched_posts += len(posts_data)

        if fetched_posts < num_posts:
            # it is not ending, we need to request for more posts...
            postfields = {
                "topic_id": topic_id,
                "direction": "forwards",
                "start_post_id": -1,
                "start_post_num": fetched_posts + 1,
                "show_from_time": -1,
                "num_to_fetch": 50,
                "a": "fetch_posts_for_topic",
                "aops_logged_in": "false",
                "aops_user_id": session_data["user_id"],
                "aops_session_id": session_data["id"],
            }

            sub_url = "/m/community/ajax.php"
            topic_page = curl(sub_url, c, post=postfields)
            parsed = json.loads(topic_page.decode("utf-8"))
            posts_data = parsed["response"]["posts"]
            # sleep to avoid over-frequent request.
            time.sleep(0.6)

    return topic_txt


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise Exception("mkdir needs permission")


def save_preview(path: str, topic_txt: str, url: str):
    # put preview into HTML template
    f = open("template.html", "r")
    fmt_str = f.read()
    f.close()
    topic_txt = topic_txt.replace("\n", "</br>")
    preview = fmt_str.replace("{PREVIEW}", topic_txt)
    preview = preview.replace("{URL}", url)
    # save preview
    with open(path, "w", encoding="utf8") as f:
        f.write(preview)


def save_json(path: str, topic_txt, url):
    with open(path, "w") as f:
        f.write(json.dumps({"url": url, "text": topic_txt}, sort_keys=True))


def get_curl():
    c = pycurl.Curl()
    c.setopt(c.CONNECTTIMEOUT, 8)
    c.setopt(c.TIMEOUT, 10)
    c.setopt(c.COOKIEJAR, file_prefix + "-cookie.tmp")
    c.setopt(c.COOKIEFILE, file_prefix + "-cookie.tmp")
    c.setopt(c.CAINFO, certifi.where())

    # redirect on 3XX error
    c.setopt(c.FOLLOWLOCATION, 1)
    return c


def list_category_topics(category, newest, oldest, c):
    # first access the page to acquire session id
    sub_url = "/community/"

    community_page = curl(sub_url, c)

    parsed = get_aops_data(community_page)
    session = parsed["AoPS.session"]
    if session is None:
        raise Exception("AoPS server format unexpected.")

    session_id = session["id"]
    user_id = session["user_id"]
    server_time = int(parsed["AoPS.bootstrap_data"]["init_time"])

    fetch_after = server_time - oldest * 24 * 60 * 60
    fetch_before = server_time - newest * 24 * 60 * 60
    while fetch_before >= fetch_after:
        print(vt100_BLUE)
        print(
            f"[category] {category},",
            "[before]",
            f'{time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(fetch_before))},',
            "[after]",
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(fetch_after)),
        )
        print(vt100_RESET)
        sub_url = "/m/community/ajax.php"

        postfields = {
            "category_type": "forum",
            "log_visit": 0,
            "required_tag": "",
            "fetch_before": fetch_before,
            "user_id": 0,
            "fetch_archived": 0,
            "fetch_announcements": 0,
            "category_id": category,
            "a": "fetch_topics",
            "aops_logged_in": "false",
            "aops_user_id": user_id,
            "aops_session_id": session_id,
        }

        try:
            navi_page = curl(sub_url, c, post=postfields)
            parsed = json.loads(navi_page.decode("utf-8"))

            resp = parsed["response"]
            if "no_more_topics" in resp and resp["no_more_topics"]:
                break

            # check response validity
            if "topics" not in resp:
                raise Exception("no key in response.")

            for topic in resp["topics"]:
                fetch_before = int(topic["last_post_time"])
                yield (category, topic, None)
        except Exception as e:
            yield (category, None, e)


def get_file_path(category_id, topic_id, post_id):
    directory = f"./tmp/{topic_id % DIVISIONS}"
    return f"{directory}/{file_prefix}-c{category_id}h{topic_id}p{post_id}"


def process_topic(file_path: str, topic_txt: str, url: str, extra_opt):
    try:
        mkdir_p(os.path.dirname(file_path))
    except Exception:
        raise
    # process TeX mode pieces
    topic_txt = convert_canonical_tex(topic_txt)
    topic_txt = replace_display_tex(topic_txt)
    topic_txt = replace_inline_tex(topic_txt)
    topic_txt = replace_dollar_tex(topic_txt)

    # do not touch time stamp if previously
    # an identical file already exists.
    jsonfile = f"{file_path}.json"
    if os.path.isfile(jsonfile):
        print(f"[exists]{jsonfile}")
        save_json(f"{file_prefix}.tmp", topic_txt, url)
        if filecmp.cmp(f"{file_prefix}.tmp", jsonfile):
            # two files are identical, do not touch
            print("[identical, no touch]")
            return
        else:
            print("[overwrite]")

    # two files are different, save files
    save_json(jsonfile, topic_txt, url)
    if extra_opt["save-preview"]:
        save_preview(f"{file_path}.html", topic_txt, url)


def crawl_category_topics(category, newest, oldest, extra_opt):
    c = get_curl()

    succ_topics = 0
    for category, topic, e in list_category_topics(category, newest, oldest, c):
        if e is not None:
            print_err(f"category {category} error: {e}")
            break
        try:
            topic_id = topic["topic_id"]
            sub_url = f"/community/c{category}h{topic_id}"
            crawl_topic_page(sub_url, category, topic_id, get_curl(), extra_opt)
        except (KeyboardInterrupt, SystemExit):
            print("[abort]")
            return "abort"
        except BaseException as e:
            print_err(f"topic {sub_url} ({e})")
            continue

        # count on success
        succ_topics += 1

        # sleep to avoid over-frequent request.
        time.sleep(0.6)

        # log crawled topics
        page_log = open(f"{file_prefix}.log", "a")
        page_log.write(f'category {category}, topic_id: {topic["topic_id"]} \n')
        page_log.close()
    return "finish"


def help(arg0):
    print(
        "DESCRIPTION: crawler script for artofproblemsolving.com."
        "\n\n"
        "SYNOPSIS:\n"
        f"{arg0} [-n | --newest <days>] "
        "[-o | --oldest <days>] "
        "[-c | --category <cnum>] "
        "[--patrol] "
        "[--save-preview] "
        "[--hook-script <script name>] "
        "[-t | --topic <topic id>] "
        "\n"
    )
    print(
        """Below are presumably the majority of topics on AoPS (as of May 2018):

    -c 3 (Middle School Math, > 33k topics)
    -c 4 (High School Math > 71k topics)
    -c 5 (Contests & Programs > 17k topics)
    -c 6 (High School Olympiads > 214k topics)
    -c 7 (College Math > 78k topics)

    Although it seems there is no way to get the age of oldest topic,
    we can enter some huge number of days to crawl all topics under given
    category, for example:

        -n 0 -o 3650 (from now to 10 years back)
    """
    )
    sys.exit(1)


def main(args):
    argv = args[1:]
    try:
        opts, _ = getopt.getopt(
            argv,
            "n:o:c:t:h",
            [
                "newest=",
                "oldest=",
                "category=",
                "topic=",
                "patrol",
                "save-preview",
                "hook-script=",
            ],
        )
    except Exception:
        help(args[0])

    # default arguments
    extra_opt = {"hookscript": "", "patrol": False, "save-preview": False}
    category = -1
    topic = -1
    newest = 0
    oldest = 0

    for opt, arg in opts:
        if opt in ("-n", "--newest"):
            newest = int(arg)
            continue
        if opt in ("-o", "--oldest"):
            oldest = int(arg)
            continue
        if opt in ("-c", "--category"):
            category = int(arg)
            continue
        elif opt in ("-t", "--topic"):
            topic = int(arg)
            continue
        elif opt in ("--patrol"):
            extra_opt["patrol"] = True
        elif opt in ("--save-preview"):
            extra_opt["save-preview"] = True
        elif opt in ("--hook-script"):
            extra_opt["hookscript"] = arg
        else:
            help(args[0])

    if topic > 0:
        sub_url = f"/community/c{category}h{topic}"
        crawl_topic_page(sub_url, category, topic, get_curl(), extra_opt)
        exit(0)

    if category > 0:
        while True:
            # crawling newest pages
            try:
                r = crawl_category_topics(category, newest, oldest, extra_opt)
            except Exception as e:
                print_err(str(e))
                quit(1)

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
