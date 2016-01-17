{% extends "message.md" %}

{% block title -%}
Waiting for build
{% endblock %}

{% block message %}
Waiting for the build status in integration pull request #{{ pr_id }}. It has not started yet.
{% endblock %}
