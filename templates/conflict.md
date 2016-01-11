:bangbang: I've encountered a conflict when I tried to merge
`{{ source.name }}` into `{{ destination.name }}`.


Here are the steps to resolve this conflict:

```
#!bash\n
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # intense conflict fixing
 $ git add <any modified file>
 $ git commit
 $ git push\n
```
I'll then relaunch the checks with your new changesets and try to merge.
