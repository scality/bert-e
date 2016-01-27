{% extends "message.md" %}

{% block title -%}
Missing Jira issue
{% endblock %}

{% block message %}
You want to merge {% branch %} into a maintenance
branch but this branch does not specify a
Jira issue id
{% endblock %}
