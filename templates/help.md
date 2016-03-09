{% extends "message.md" %}

{% block title -%}
Help page
{% endblock %}

{% block message %}
You will find some user & technical documentation [online](https://docs.scality.com/display/RE/Wall-E's+user+documentation).

The following options and commands are available at this time.

## Options ##

{% if options %}
name   | description  | privileged
------ | ------------ | ------------
{% for option in options -%}
:arrow_right: **{{option}}** | {{options[option].help}} | {% if options[option].privileged %} :star: {% endif %}
{% endfor %}
{% else %}
*No options available at this time, please check again later.*
{% endif %}

## Commands ##

{% if commands %}
name   | description  | privileged
------ | ------------ | ------------
{% for cmd in commands -%}
:arrow_right: **{{cmd}}** | {{commands[cmd].help}} | {% if commands[cmd].privileged %} :star: {% endif %}
{% endfor %}
{% else %}
*No commands available at this time, please check again later.*
{% endif %}
{% endblock %}
