{%- extends 'basic.tpl' -%}
{% block input %}
<div class="inner_cell">
<div class="input_area">
```{% if nb.metadata.language_info %}{{ nb.metadata.language_info.name }}{% endif %}
{{ cell.source}}
```
</div>
</div>
{%- endblock input %}

{% block markdowncell scoped %}
{%- if cell.is_leading_cell is defined -%}
<div class="hidden">
{%- endif -%}
{{- super() -}}
{%- if cell.is_leading_cell is defined -%}
</div>
{%- endif -%}
{%- endblock markdowncell %}