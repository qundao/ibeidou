import json
import logging
import re
import shutil
import unicodedata
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm


def dict_to_yaml_frontmatter(data):
    yaml_str = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return "\n".join(["---", yaml_str.strip(), "---"])


def clean_title(x):
    x = unicodedata.normalize("NFKC", x)  # 全角字符转换
    x = re.sub(r"\s*[•·]\s*", "·", x.strip())
    x = re.sub(r"\s+", " ", x)
    x = re.sub(r"[＞〉]", ">", x)
    x = re.sub(r"[＜〈]", "<", x)
    x = re.sub(r"\s*([《【（<(\[])\s*", r"\1", x)
    x = re.sub(r"\s*([》】）>)\]])\s*", r"\1", x)
    x = re.sub(r"\s*[-—]{2,}\s*", "——", x)
    x = re.sub(r"([一二三四五六七八九十]期)\s+(天枢|天璇|天玑|天权|玉衡|开阳|摇光)", r"\1·\2", x)
    x = re.sub(r"([\u4e00-\u9fff])\s*:\s*", r"\1：", x)  # 修正中文后的引号
    return x


def process_series(x):
    if x and "一名在港" not in x:
        return [x]
    return []


def get_more_tags(x):
    out = []
    for v in re.findall("<([^>]+)>|【（[^】]+）】", x):
        out.append(v.strip())
    return out


def process_tags(x):
    # x: keywords
    result = x["tags-more"] if x["tags-more"] else []
    for v in x["keywords"]:
        if v == x["title"] or "——" in v or "《" in v or "……" in v:
            continue
        if re.sub(r"[\.\da-zA-Z\s（）()]", "", v) == "":
            continue
        result.extend(re.split(r"[，,。！？<>【】、：:;；·•＜&\s]", v))
    result = set(result)
    result2 = [v.strip() for v in result if v.strip() and v != x["title"]]
    result2 = [re.sub(r"[（(][^)）]*([)）]|$)", "", v) for v in result2]
    result2 = [re.sub(r"^[^））]*[）)]", "", v) for v in result2]
    result2 = [re.sub(r"＞.*", "", v) for v in result2]
    result2 = [v.strip() for v in result2 if len(v.strip()) > 1]
    result3 = []
    for v in set(result2):
        if "“" not in v and "”" in v:
            v = "“" + v
        result3.append(v)
    result3 = sorted(set(result3))
    return result3


def clean_brackets(x):
    x = re.sub(r"[（(][^)）]*([)）]|$)", "", x)
    x = re.sub(r"^[^））]*[）)]", "", x)
    x = re.sub(r"@|文/|(<?七星(说法|百科|说法)[\s/·，,>]+)", "", x)
    x = re.sub("/.*", "", x)
    out = [v.strip("<> ") for v in re.split(r"[\s,、：；;:·]", x) if v.strip()]
    out2 = [v for v in out if len(re.findall("荐书人|大学|中科院国家|青年空间|图书馆", v)) == 0]
    if len(out2) == 0:
        out2 = out
    out3 = list(dict.fromkeys(out2))
    return out3


def process_post(post_file):
    img_pattern = r"\[(!\[[^\]]*\]\([^)]+.(?:jpg|jpeg|gif|png)\))\]\([^)]+.(?:jpg|jpeg|gif|png)\)"

    with open(post_file, encoding="utf-8") as f:
        text = f.read()
    # remove image link
    text = re.sub(img_pattern, r"\1", text)
    # ignore h1
    lines = text.split("\n")

    output = []
    start = True
    for line in lines:
        line = line.strip()
        line = re.sub(r"\*\* +\*\*", "", line)
        line = re.sub(r"^[#\s]+$", "", line)

        if line == "":
            continue
        if line.startswith("# ") and start:
            output.append(f"<!-- {line} -->")
        else:
            start = False
            if not line.startswith("#"):  # split by spaces
                line = re.sub(
                    r"([^a-z\d.,?!:'\"\[\]])\s+([^a-z\d.,?!:'\"\[\]])",
                    r"\1\n\n\2",
                    line,
                    flags=re.IGNORECASE,
                )
            else:
                line = re.sub(r"\*\*", "", line)
                line = re.sub(r"(#+)([^# ].+)(#+)", r"\1 \2", line)

            line = re.sub(r"\n+责编：", "；责编：", line)
            line = re.sub(r"^#+ (链接|原文)", r"> \1", line)
            output.append(line)

    result = "\n\n".join(output)
    result = re.sub(r"\)\s*(!\[)", r"\)\n\1", result)
    result = re.sub(r"\n[\s#]+(!\[)", r"\n\1", result)

    result = re.sub(r"\s+\n(\s*\n)+", "\n\n", result)
    return result


def run(base_dir, output_dir):
    meta_files = sorted(Path(base_dir).rglob("*.json"))
    logging.info(f"meta.json = {len(meta_files)}")
    if len(meta_files) == 0:
        return

    logging.info("Read meta.json files")
    meta_data = []
    for file in tqdm(meta_files):
        with open(file, encoding="utf-8") as f:
            result = json.load(f)
        result["path"] = file.as_posix()
        meta_data.append(result)

    df_meta = pd.DataFrame(meta_data)
    df_meta = df_meta.sort_values(["date", "name"])
    df_meta = df_meta.reset_index(drop=True)
    df_meta["index"] = df_meta.index + 1
    df_meta["index"] = df_meta["index"].apply(lambda x: f"{x:04d}")
    df_meta["year"] = df_meta["date"].apply(lambda x: x.split("-")[0]).astype(int)
    df_meta["name"] = df_meta["name"].apply(clean_title)
    df_meta["title"] = df_meta["name"]  # 原title不用
    df_meta["author"] = df_meta["author"].apply(clean_title)
    df_meta["authors"] = df_meta["author"].apply(clean_brackets)

    # 处理系列
    df_meta["series"] = df_meta["column"].apply(process_series)
    tmp_series = df_meta["series"].explode().value_counts().index.tolist()
    df_meta["tags-more"] = df_meta["name"].apply(get_more_tags)

    # 处理标签: 仅保留高频的
    min_tag_count = 5
    df_meta["tags-todo"] = df_meta.apply(process_tags, axis=1)
    tmp_tags = df_meta["tags-todo"].explode().value_counts()
    top_tags = tmp_tags[tmp_tags >= min_tag_count].index.tolist()
    top_tags += [v for v in tmp_tags[tmp_tags < min_tag_count].index.tolist() if "专题" in v]
    top_tags = set(top_tags) - set(tmp_series)
    df_meta["tags"] = df_meta["tags-todo"].apply(lambda x: sorted(set(x) & top_tags))

    # 清空保存目录
    if Path(output_dir).exists():
        logging.info(f"Clean dir = {output_dir}")
        shutil.rmtree(output_dir)

    # 输出
    out_cols = ["title", "date", "authors", "series", "tags"]
    data = df_meta.to_dict("records")
    logging.info("Copy files")
    for entry in tqdm(data):
        meta = {k: entry.get(k) for k in out_cols}
        meta_file = Path(entry["path"])
        parent_dir = meta_file.parent
        post_file = meta_file.with_name("post.md")
        cover_file = Path(parent_dir, entry["cover"])
        files = sorted(parent_dir.glob("*.*"))
        files = [v for v in files if v.name != "post.md"]

        save_dir = Path(output_dir, str(entry["year"]), str(entry["index"]))
        save_dir.mkdir(parents=True, exist_ok=True)

        meta_text = dict_to_yaml_frontmatter(meta)
        post = process_post(post_file)
        post_all = "\n\n".join([meta_text, post.strip()])

        for file in files:
            shutil.copyfile(file, Path(save_dir, file.name))
        if cover_file.exists():
            shutil.copyfile(cover_file, Path(save_dir, "featured" + cover_file.suffix))

        save_file = Path(save_dir, "_index.md")
        with open(save_file, "w", encoding="utf-8") as f:
            f.write(post_all.strip() + "\n")


if __name__ == "__main__":
    fmt = "%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    base = "articles" # ibeidou-articles
    target = "output" # content/articles
    run(base, target)
