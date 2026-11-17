"""Read-only execution-plan report; never prints SQL, user data or credentials."""
import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from dms import services


class Command(BaseCommand):
    help='Katalogabfrage mit EXPLAIN ANALYZE messen; enthält keine Dokumentinhalte im Bericht.'
    def add_arguments(self,parser):
        parser.add_argument('username')
    def handle(self,*args,**options):
        user=get_user_model().objects.get(username=options['username'])
        captured=[]
        def capture(execute,sql,params,many,context):
            if sql.lstrip().startswith('WITH input AS'):captured.append((sql,params))
            return execute(sql,params,many,context)
        with connection.execute_wrapper(capture):services.visible_versions(user,catalog_only=True,limit=30)
        sql,params=captured[0]
        with connection.cursor() as cursor:
            cursor.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+sql,params)
            plan=cursor.fetchone()[0][0]
        self.stdout.write(json.dumps({'planning_ms':plan['Planning Time'],'execution_ms':plan['Execution Time'],'actual_rows':plan['Plan']['Actual Rows'],'shared_hit_blocks':plan['Plan'].get('Shared Hit Blocks',0)}))
