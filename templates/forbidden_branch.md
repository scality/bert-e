{% extends "message.md" %}

{% block title -%}
Invalid branch name
{% endblock %}

{% block message %}
I cannot merge the branch `{{ source.name }}` into
`{{ destination.name }}`.
The only patterns accepted in the source branch are :
```
feature/*
bugfix/*
improvement/*
project/*
```
Please rename your branch and create a new pull request.
{% endblock %}
