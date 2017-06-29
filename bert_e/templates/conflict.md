{% extends "message.md" %}

{% block title -%}
Conflict
{% endblock %}

{% block message %}
{% if origin %}
There is a conflict between your branch `{{ feature_branch.name }}` and the
destination branch `{{ wbranch.dst_branch.name }}`.

Please resolve the conflict on **the feature branch** (`{{ feature_branch.name }}`).

```
#!bash
 $ git fetch
 $ git checkout origin/{{ feature_branch.name }}
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
{% else %}
A conflict has been raised during the {{ "creation" if empty else "update" }} of
integration branch `{{ wbranch.name }}` with contents from `{{ source.name }}`
and `{{ wbranch.dst_branch.name }}`.

{% if empty -%}
**I have not created the integration branch.**
{%- else -%}
Please resolve the conflict on **the integration branch** (`{{ wbranch.name }}`).
{%- endif %}


Here are the steps to resolve this conflict:

```
#!bash
 $ git fetch
 {% if empty -%}
 $ git checkout -B {{ wbranch.name }} origin/{{ wbranch.dst_branch.name }}
{%- else -%}
 $ git checkout {{ wbranch.name }}
 $ git pull  # or "git reset --hard origin/{{ wbranch.name }}"
 $ git merge origin/{{ wbranch.dst_branch.name }}
 $ # <intense conflict resolution>
{%- endif %}
 $ git merge origin/{{ source.name }}
 $ # <intense conflict resolution>
 $ git push -u origin {{ wbranch.name }}
```
{%endif%}
{% endblock %}
