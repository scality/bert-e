{% extends "message.md" %}

{% block title -%}
Ready to Merge
{% endblock %}

{% block message %}
The pull request is now ready to be merged, use the following command to
merge it:
```
@{{ bert_e }} merge
```
{% endblock %}
