{% extends "message.md" %}

{% block title -%}
Build failed
{% endblock %}

{% block message %}
The {% if build_url %}[build]({{ build_url }}){% else %}build{% endif %} did not succeed in branch {{ branch }}.
{% endblock %}
