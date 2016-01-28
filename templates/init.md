{% extends "message.md" %}

{% block title -%}
Hello @{{ author }},
{% endblock %}

{% block message %}
My name is Wall-E. My role is to assist you with the merge of this
pull request. Please type `@scality_wall-e help` to get
information on this process.

{% include 'status_report.md' %}
{% endblock %}
