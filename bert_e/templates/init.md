{% extends "message.md" %}

{% block title -%}
Hello {{ author }},
{% endblock %}

{% block message %}
My role is to assist you with the merge of this
pull request. {% if frontend_url
%}Please type `@{{ bert_e }} help` to get information
on this process, or consult the [user documentation](
{{ frontend_url }}/doc/user).{% endif %}

{% if options %}
<details>
  <summary><b>Available options</b></summary>

  name   | description  | privileged   | authored
  ------ | ------------ | ------------ |----------
  {% for option in options -%}
  `/{{option}}` | {{options[option].help}} | {% if options[option].privileged %} :star: {% endif %} | {% if options[option].authored %} :writing_hand: {% endif %}
  {% endfor %}

</details>
{% endif %}

{% if commands %}
<details>
  <summary><b>Available commands</b></summary>

  name   | description  | privileged
  ------ | ------------ | ------------
  {% for cmd in commands -%}
  `/{{cmd}}` | {{commands[cmd].help}} | {% if commands[cmd].privileged %} :star: {% endif %}
  {% endfor %}
</details>
{% endif %}

{% include 'status_report.md' %}
{% endblock %}
