from filter_pull_requests import filter_pr
import wall_e
import sys
reload(sys)
sys.setdefaultencoding('utf-8')

p = filter_pr('mvaude', '***REMOVED***', 'maxime.vaude@scality.com', 'scality',
              'ring', destination='development/*', source='', author='^((?!Wall).)*$',
              close_source_branch='', state='', title='', created_on='',
              updated_on='')

def handle(pull_request_id,
           options=[],
           reference_git_repo='/home/mvaude/bitbucket/ring',
           no_comment=True,
           interactive=False,
           backtrace=True):
    import sys
    sys.argv = ["wall-e.py"]
    for option in options:
        sys.argv.append('-o')
        sys.argv.append(option)
    if no_comment:
        sys.argv.append('--no-comment')
    if interactive:
        sys.argv.append('--interactive')
    if backtrace:
        sys.argv.append('--backtrace')
    sys.argv.append('--quiet')
    sys.argv.append('--settings')
    sys.argv.append('ring')
    sys.argv.append('--slug')
    sys.argv.append('ring')
    sys.argv.append(str(pull_request_id))
    sys.argv.append('***REMOVED***')
    return wall_e.main()

for (pr_id, pr_log) in p.items():
    try:
        handle(pr_id)
    except Exception as e:
        print('{0} {2} {1}'.format(pr_id, pr_log.decode('utf-8'), e.__class__.__name__))



#from pprint import pprint
#pprint(p)
print(len(p))
