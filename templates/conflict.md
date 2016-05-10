{% extends "message.md" %}

{% block title -%}
Conflict during merge
{% endblock %}

{% block message %}
A conflict has been raised during the merge of `{{ source.name }}`
into integration branch `{{ destination.name }}`.

{% if origin %}
Please resolve the conflict **on the feature branch** (`{{ feature_branch.name }}`).
{% else %}
Please resolve the conflict on **the integration branch**.

Here are the steps to resolve this conflict:

```
#!bash
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # <intense conflict resolution>
 $ git push origin HEAD:{{ destination.name }}
```

After the push, please comment this pull request to resume the procedure.
{%endif%}
{% endblock %}
