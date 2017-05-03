{% extends "message.md" %}

{% block title -%}
Build failed
{% endblock %}

{% block message %}
The {% if build_url %}[build]({{ build_url }}){% else %}build{% endif %}{% if commit_url %} for [commit]({{ commit_url }}){% endif %} did not succeed in branch {{ branch }}.
{% endblock %}
