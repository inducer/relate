{%- extends 'basic.tpl' -%}

{# This is to prevent code_cell being process by markdown_to_html #}

{% block input %}<pre class="relate_tmp_pre">{{ super() }}</pre>
{%- endblock input %}

{# This is to remove the empty cells ahead of markdown_cells #}
{% block empty_in_prompt -%}
{%- endblock empty_in_prompt %}