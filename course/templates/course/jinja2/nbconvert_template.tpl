{%- extends 'basic.tpl' -%}

{# This is changed to prevent code_cell being process by markdown twice #}

{% block input %}
<div class="inner_cell">
<div class="input_area">
```{% if nb.metadata.language_info %}{{ nb.metadata.language_info.name }}{% endif %}
{{ cell.source}}
```
</div>
</div>
{%- endblock input %}
