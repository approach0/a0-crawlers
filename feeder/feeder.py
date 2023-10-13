import os
import sys
import json
import requests
import argparse
import configparser
from tqdm import tqdm
from urllib.parse import urlparse
from collections.abc import Iterable


def file_walk(directory_or_filepath):
    path = os.path.expanduser(directory_or_filepath)
    if os.path.isfile(path):
        ext = path.split('.')[-1]
        yield path, ext
    for dirname, dirs, files in os.walk(path):
        for f in files:
            ext = f.split('.')[-1]
            yield os.path.join(dirname, f), ext


def json_walk(directory, allow_extensions, max_items):
    cnt = 0
    for path, ext in file_walk(directory):
        if ext not in allow_extensions:
            continue
        with open(path, 'r') as fh:
            if ext == 'jsonl':
                for ln, line in enumerate(fh):
                    cnt += 1
                    if cnt > max_items:
                        return
                    else:
                        yield f'{path}:{ln}', line
            elif ext == 'json':
                cnt += 1
                if cnt > max_items:
                    return
                else:
                    yield f'{path}', fh.read()
            else:
                raise NotImplemented


def send_json(url, send_j):
    headers = {'content-type': 'application/json'}
    r = requests.post(url, json=send_j, headers=headers)
    return json.loads(r.content.decode("utf-8"))


def send_to_each_indexd(indexd_urls, send_j, abort_value=1):
    for url in indexd_urls:
        try:
            res = send_json(url, send_j)
        except Exception as err:
            print(err)
            if abort_value >= 0:
                quit(abort_value)
    return res


def feed(indexd_urls, args, config):
    allow_extensions = json.loads(config['allow_extensions'])
    index_field_map = json.loads(config['index_field_map'])
    max_items = config.getint('max_items') or float('inf')
    progress_bar = config.getboolean('progress_bar')

    if progress_bar:
        print('Counting total #documents ...')
        cnt = len(list(_ for _ in
            json_walk(args.CORPUS_PATH, allow_extensions, max_items))
        )
    else:
        cnt = None

    walker = json_walk(args.CORPUS_PATH, allow_extensions, max_items)
    progress = tqdm(walker, total=cnt)
    for src_id, j_str in progress:
        try:
            j = json.loads(j_str)
        except Exception as e:
            print(e, '\n', j_str)
            continue
        send_j = {}
        for key, value in index_field_map.items():
            send_j[key] = go_thro_pipelines(config, src_id, j, value)
            if send_j[key] is not None:
                send_j[key] = send_j[key].strip()
        if args.preview:
            print('src_id:', src_id)
            print('preview:', send_j, end='\n\n')
            #print(send_j['content'])
        else:
            res = send_to_each_indexd(indexd_urls, send_j)
            progress.set_description(f"Indexed doc: {res['docid']}")


def go_thro_pipelines(config, src_id, j, value):
    if isinstance(value, str):
        return eval(value)
    elif isinstance(value, Iterable):
        last_val = None
        for v in value:
            last_val = eval(v)
        return last_val
    else:
        raise NotImplemented


def pipeline__url2site(val):
    return urlparse(val)[1]


def pipeline__use_lancaster_stemmer(config, val):
    pya0_path = config['pya0_path']
    sys.path.insert(0, pya0_path)
    from pya0 import preprocess, use_stemmer
    use_stemmer(name='lancaster')
    return preprocess(val, expansion=False)


def pipeline__use_porter_stemmer(config, val):
    pya0_path = config['pya0_path']
    sys.path.insert(0, pya0_path)
    from pya0 import preprocess, use_stemmer
    use_stemmer(name='porter')
    return preprocess(val, expansion=False)


def pipeline__replace_dollars(config, val):
    from replace_post_tex import replace_dollar_tex
    return replace_dollar_tex(val)


if __name__ == '__main__':
    default_url = 'http://localhost:8934/index'
    parser = argparse.ArgumentParser(
        description='Approach Zero Index Daemon JSON Feeder.'
    )

    # positionals
    parser.add_argument(
        'CONFIG', help='feeder config file', type=str
    )
    parser.add_argument(
        'CORPUS_PATH', help='corpus path', type=str
    )

    # optionals
    parser.add_argument(
        '--indexd-url', help=f'index daemon URL. (default: {default_url})',
        type=str, action='append'
    )
    parser.add_argument(
        '--corpus', help='corpus name', type=str, default='DEFAULT'
    )
    parser.add_argument(
        '--bye', help='ask indexd to terminate at the end',
        action='store_true'
    )
    parser.add_argument(
        '--preview', help='preview the feeding JSON',
        action='store_true'
    )
    args = parser.parse_args()

    # parse config file
    config = configparser.ConfigParser()
    config.read(args.CONFIG)

    # overwrite indexd_url (args have higher priority) in config
    if args.indexd_url is not None:
        config.set('DEFAULT', 'indexd_url', json.dumps(args.indexd_url))

    # print out parameters
    print('---' * 5, 'ARGS', '---' * 5)
    print(args)
    print('---' * 5, 'CONFIG', '---' * 5)
    for key, value in config[args.corpus].items():
        print(key, value)
    print('---' * 5, 'END', '---' * 5)

    # feed data
    section_config = config[args.corpus]
    indexd_urls = json.loads(section_config['indexd_url'])
    feed(indexd_urls, args, section_config)

    # send BYE command on request
    if args.bye:
        print('\n Now, send BYE to terminate indexers ... \n')
        send_to_each_indexd(indexd_urls, {'cmd': 'BYE'}, abort_value=0)
