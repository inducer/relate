# Downloaded from https://github.com/mayoff/python-markdown-mathjax/issues/3
from __future__ import annotations

import markdown
from markdown.inlinepatterns import Pattern
from markdown.postprocessors import Postprocessor


class MathJaxPattern(Pattern):
    def __init__(self):
        super().__init__(r"(?<!\\)(\$\$?)(.+?)\2")

    def handleMatch(self, m):
        print(f"{m.group(0)=}")
        from xml.etree.ElementTree import Element
        node = Element("mathjax")
        from markdown.util import AtomicString
        node.text = AtomicString(m.group(2) + m.group(3) + m.group(2))
        return node


class MathJaxPostprocessor(Postprocessor):
    def run(self, text):
        text = text.replace("<mathjax>", "")
        text = text.replace("</mathjax>", "")
        return text


class MathJaxExtension(markdown.Extension):
    def extendMarkdown(self, md):
        # Needs to come before escape matching because \ is pretty important in LaTeX
        # inlinepatterns in Python-Markdown seem to top out at 200-ish?
        # https://github.com/Python-Markdown/markdown/blob/0b5e80efbb83f119e0e38801bf5b5b5864c67cd0/markdown/inlinepatterns.py#L53-L95
        md.inlinePatterns.register(MathJaxPattern(), "mathjax", 1000)
        print(md.inlinePatterns)
        md.postprocessors.register(MathJaxPostprocessor(md), "mathjax", 0)


def makeExtension(configs=None):
    return MathJaxExtension(configs)
