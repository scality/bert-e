{% extends "message.md" %}

{% block title -%}
Build failed
{% endblock %}

{% block message %}
The {% if build_url is defined and build_url is not none %}[build]({{ build_url }}){% else %}build{% endif %} did not succeed in integration pull request #{{ pr_id }}.
{% endblock %}
