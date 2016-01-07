Automatically generate course outlines
======================================

The tool in this directory generates HTML files that can be included into
RELATE course pages to produce outline trees like the ones on this page:

https://relate.cs.illinois.edu/course/cs598apk-f15/

To generate the tree, simply pass a YAML file like the provided example
(``outline-tree.yml``) to the script::

    ./make-tree-html outline-tree.yml -o outline-tree.html

You can then include the generated HTML into a RELATE page with the following
snippet of HTML::

    <div id="outline-tree" markdown="1">
    {% include "outline-tree.html" %}
    </div>

    <script type="text/javascript">
      $('#outline-tree').jstree({
            "core": {
                "themes": {
                    'name': 'default',
                    'responsive': true
                }
            },
            "state" : {
                "key" : "outline-cs598-f15", /* this should be unique per RELATE instance */
                "filter": function (k) { delete k.core.selected; return k; }
                },
            "plugins" : ["state"]
        })
      .bind("select_node.jstree", function (e, data)
          {
              var href = data.node.a_attr.href;
              if (href.length > 1)
                  window.open(href, "_blank");
          });
    </script>

In the long run, support for something like this will probably end up in RELATE
itself, but for now, this is the (slightly clunky) way of producing a course
outline.

The script also has the ability to scan directories full of PDF and/or IPython
notebook files. These are assumed to be named as follows:

*    ``00-SECTION/NAME.ipynb``
*    ``00-SECTION.pdf``

where ``00`` is the section number, and uppercase letters can represent any
name.  They are inserted into the outline tree into the node with the matching
``section:`` number.
