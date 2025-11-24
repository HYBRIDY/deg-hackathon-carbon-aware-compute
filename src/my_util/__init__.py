import re
from typing import Dict

from . import my_a2a


def parse_tags(str_with_tags: str) -> Dict[str, str]:
    """Extract <tag>value</tag> pairs from a string."""

    tags = re.findall(r"<(.*?)>(.*?)</\1>", str_with_tags, re.DOTALL)
    return {tag: content.strip() for tag, content in tags}


__all__ = ["parse_tags", "my_a2a"]


if __name__ == "__main__":  # pragma: no cover
    test_str = "<tag1>Hello</tag1> some text <tag2>World</tag2>"
    print(parse_tags(test_str))
