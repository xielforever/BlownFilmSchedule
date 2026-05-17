import requests

# Login
r = requests.post('http://localhost:8000/api/auth/login', data={'username':'admin','password':'admin123'})
token = r.json()
print('Login:', token['role'], token['name'])

at = token['access_token']
headers = {'Authorization': 'Bearer ' + at}

# Dashboard
r = requests.get('http://localhost:8000/api/dashboard/summary', headers=headers)
d = r.json()
print('Dashboard: {} orders, {}% on-time, {}kg scrap, {}% util'.format(
    d['total_orders'], d['on_time_rate'], d['total_scrap_kg'], d['avg_utilization']))

# Gantt
r = requests.get('http://localhost:8000/api/schedule/gantt', headers=headers)
g = r.json()
print('Gantt: {} tasks, {} maint windows'.format(len(g['tasks']), len(g['maintenance'])))

# Orders
r = requests.get('http://localhost:8000/api/orders', headers=headers)
o = r.json()
print('Orders: {} total'.format(o['total']))

# Machines
r = requests.get('http://localhost:8000/api/machines', headers=headers)
m = r.json()
print('Machines: {}'.format(len(m)))

print('ALL API TESTS PASSED')
