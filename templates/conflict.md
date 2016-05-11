{% extends "message.md" %}

{% block title -%}
Conflict during merge
{% endblock %}

{% block message %}
A conflict has been raised during the merge of `{{ source.name }}`
into integration branch `{{ destination.name }}`.

{% if origin %}
Please resolve the conflict on **the feature branch** (`{{ feature_branch.name }}`).

```
#!bash
 $ git fetch
 $ git checkout {{ feature_branch.name }}
 $ git merge origin/{{ dev_branch.name }}
 $ # <intense conflict resolution>
 $ git push origin HEAD:{{ feature_branch.name }}
```

{% if source.name == dev_branch.name -%}
Unfortunately, I cannot recover from this particular case automatically (see
RELENG-1439). Once you have resolved the conflict, you will have to manually
delete all `w/*` branches related to this pull request
(using `git push origin :<branch-name> `).

Once done, please **decline the old integration pull requests** and comment
this pull request to resume the merge process.
{% endif%}
{% else %} Please
resolve the conflict on **the integration branch** (`{{ destination.name }}`).

Here are the steps to resolve this conflict:

```
#!bash
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # <intense conflict resolution>
 $ git push origin HEAD:{{ destination.name }}
```
{%endif%}
{% endblock %}
