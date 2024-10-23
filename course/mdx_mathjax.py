# Downloaded from https://github.com/mayoff/python-markdown-mathjax/issues/3
from __future__ import annotations

import markdown
from markdown.inlinepatterns import Pattern
from markdown.postprocessors import Postprocessor


class MathJaxPattern(Pattern):
    def __init__(self):
        super().__init__(r"(?<!\\)(\$\$?)(.+?)\2")

    def handleMatch(self, m):
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
        md.inlinePatterns.register(MathJaxPattern(), "mathjax",
                                   md.inlinePatterns.get_index_for_name("escape") + 1)
        md.postprocessors.register(MathJaxPostprocessor(md), "mathjax", 0)


def makeExtension(configs=None):
    return MathJaxExtension(configs)
