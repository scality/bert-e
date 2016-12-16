{% extends "message.md" %}

{% block title -%}
Jira issue not found
{% endblock %}

{% block message %}
The Jira issue {{ issue }} was not found.
{% endblock %}
