{% extends "message.md" %}

{% block title -%}
Not authorized.
{% endblock %}

{% block message %}
I'm afraid I cannot do that, @{{ author }}:

> {{ comment|replace('\n', '\n> ') }}

{% if self_pr %}
You cannot use `{{ command }}` in your own pull request.
{% else %}
You don't have enough credentials to use `{{ command }}`.
{% endif %}

Please **edit** or **delete** the corresponding comment so I can move on.
{% endblock %}
