{% extends "message.md" %}

{% block title -%}
Hello {{ author }},
{% endblock %}

{% block message %}
My role is to assist you with the merge of this
pull request. {% if frontend_url and frontend_url != ''
%}Please type `@{{ bert_e }} help` to get information
on this process, or consult the
[user documentation]({{ frontend_url }}/doc/user).{% endif %}

{% if tasks %}
I have created below the minimum set of tasks expected to be performed during
this review.
{% endif%}

{% include 'status_report.md' %}
{% endblock %}
