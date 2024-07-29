# Downloaded from https://github.com/mayoff/python-markdown-mathjax/issues/3
from __future__ import annotations

import markdown
from markdown.postprocessors import Postprocessor


class MathJaxPattern(markdown.inlinepatterns.Pattern):  # type: ignore
    def __init__(self):
        markdown.inlinepatterns.Pattern.__init__(self, r"(?<!\\)(\$\$?)(.+?)\2")

    def handleMatch(self, m):
        node = markdown.util.etree.Element("mathjax")
        node.text = markdown.util.AtomicString(m.group(2) + m.group(3) + m.group(2))
        return node


class MathJaxPostprocessor(Postprocessor):
    def run(self, text):
        text = text.replace("<mathjax>", "")
        text = text.replace("</mathjax>", "")
        return text


class MathJaxExtension(markdown.Extension):
    def extendMarkdown(self, md, md_globals):
        # Needs to come before escape matching because \ is pretty important in LaTeX
        md.inlinePatterns.add("mathjax", MathJaxPattern(), "<escape")
        md.postprocessors["mathjax"] = MathJaxPostprocessor(md)


def makeExtension(configs=None):
    return MathJaxExtension(configs)
