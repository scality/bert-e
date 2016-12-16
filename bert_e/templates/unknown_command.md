{% extends "message.md" %}

{% block title -%}
Unknown command
{% endblock %}

{% block message %}
I didn't understand this comment by @{{ author }}:

> {{ comment|replace('\n', '\n> ') }}

I don't know what `{{ command }}` means.

Please **edit** or **delete** the corresponding comment so I can move on.
{% endblock %}
