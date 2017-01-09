{% extends "message.md" %}

{% block title -%}
Hello {{ author }},
{% endblock %}

{% block message %}
My role is to assist you with the merge of this
pull request. Please type `@{{ bert_e }} help` to get
information on this process.

{% if tasks %}
I have created below the minimum set of tasks expected to be performed during
this review.
{% endif%}

{% include 'status_report.md' %}
{% endblock %}
