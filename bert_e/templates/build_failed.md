{% extends "message.md" %}

{% block title -%}
Build failed
{% endblock %}

{% block message %}
The {% if build_url -%}[build]({{ build_url }}) {% else -%}build {% endif -%}
{% if commit_url -%}for [commit]({{ commit_url }}) {% endif %}did not succeed in branch
{%- if githost == 'bitbucket' %} [{{ branch.name }}](https://bitbucket.org/{{ owner }}/{{ slug }}/branch/{{ branch.name }}?dest={{ branch.dst_branch }})
{%- elif githost == 'github' %} [{{ branch.name }}](https://github.com/{{ owner }}/{{ slug }}/compare/{{ branch.dst_branch }}...{{ branch.name }})
{%- else %} `{{ branch.name }}`
{%- endif -%}
{% endblock %}
