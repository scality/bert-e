{% extends "message.md" %}

{% block title -%}
Incorrect command syntax
{% endblock %}

{% block message %}
{% if comment is defined %}
I didn't understand this comment{% if author is defined %} by @{{ author }}{% endif %}:

> {{ comment|replace('\n', '\n> ') }}

{% endif %}
{% if command is defined %}
It seems that the syntax of the option `{{ command }}` is incorrect. The correct usage is:

```
@{{ robot }} {{ usage }}
```

or, using the shorthand (alone in its comment, or only followed by other
`/` options):

```
/{{ usage }}
```
{% else %}
It seems that your command syntax is incorrect. The correct usage is:

```
@{{ robot }} option[=argument]
```
{% endif %}

Please **edit** or **delete** the corresponding comment so I can move on.

{% endblock %}
