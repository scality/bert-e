{% extends "message.md" %}

{% block title -%}
Incorrect command syntax
{% endblock %}

{% block message %}
It seems that your command syntax is incorrect.{% if extra_message %} {{ extra_message }}{% endif %} The correct usage is:

```
@{{ robot }} option[=argument]
```

Please **edit** or **delete** the corresponding comment so I can move on.

{% endblock %}
