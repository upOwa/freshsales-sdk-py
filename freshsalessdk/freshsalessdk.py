import copy
import json
import logging
import time

import requests

logger = logging.getLogger(__name__)


class APIBase:
    def __init__(self, resource_type, domain, api_key, resource_type_singular=None, default_params=None):
        self.resource_type = resource_type
        self.resource_type_singular = resource_type_singular
        # best guess is to remove last letter
        if self.resource_type_singular is None:
            self.resource_type_singular = self.resource_type[0:-1]
        self.domain = domain
        self.api_key = api_key
        self.default_params = default_params
        if not self.default_params:
            self.default_params = {}

    def _request_generic(self, method, path, params=None, data=None):
        """Create a HTTP request.

        Parameters:
            method (callback): method to call (e.g. `requests.get`, `requests.post`)
            path (str): path for the wanted API. Should start with a '/'
            params (dict): HTTP GET parameters for the wanted API.
            data (Any): HTTP POST payload as Python/JSON object for the wanted API.

        Returns:
            A response from the request (dict, or bool in some cases like deleting a contact).
        """
        assert method is not None
        assert path is not None
        assert path.startswith('/')
        if not params:
            params = {}
        if not data:
            data = {}
        api_headers = {'Authorization': f'Token token={self.api_key}'}
        api_params = copy.deepcopy(self.default_params)

        for k in params:
            # ignore all unused params
            if not params[k] is None:
                p = params[k]

                # convert boolean to lowercase string
                if isinstance(p, bool):
                    p = str(p).lower()

                api_params[k] = p

        api_path = f'https://{self.domain}.freshsales.io/api{path}'
        logger.debug('calling %s %s passing params %s', method.__name__, api_path, api_params)
        response = method(
            url=api_path,
            headers=api_headers,
            params=api_params,
            json=data
        )
        # raise exception if not 200
        response.raise_for_status()

        res = json.loads(response.text)
#        logger.debug('res = %s', res)
        return res

    def _get_generic(self, path, params=None):
        """Create a HTTP GET request.

        Parameters:
            params (dict): HTTP GET parameters for the wanted API.
            path (str): path for the wanted API. Should start with a '/'

        Returns:
            A response from the request (dict).
        """
        return self._request_generic(requests.get, path, params)

    def _get_views(self):
        return self._get_generic(path=f'/{self.resource_type}/filters')['filters']

    @staticmethod
    def _find_obj_by_id(objs, id):
        for o in objs:
            if o['id'] == id:
                return o
        return None

    def _normalize(self, obj, container):
        """
        Every class should normalize it if it wants to do any normalization of the object.
        E.g. contact object has an owner_id and list of users is in the container. We can fetch
        the owner object and attach it to the contact object which makes things easier for the client
        """
        raise NotImplementedError('this should be overridden')

    def _get_all_generator(self, view_id, limit=None):
        page = 1
        num = 0
        while True:
            start_time = time.time()
            params = {'page': page}
            res = self._get_generic(
                path=f'/{self.resource_type}/view/{view_id}', params=params)
            total_pages = res['meta']['total_pages']
            end_time = time.time()
            logger.debug('got page %s of %s in %s seconds',
                         page, total_pages, end_time-start_time)

            objs = res[self.resource_type]
            for obj in objs:
                self._normalize(obj=obj, container=res)
                num = num + 1
                if limit and num > limit:
                    return
                yield obj

            page = page + 1
            if page > total_pages:
                break

    def _get_by_id(self, id):
        res = self._get_generic(path=f'/{self.resource_type}/{id}')
        v = res[self.resource_type_singular]
        self._normalize(obj=v, container=res)
        return v

    def get_views(self):
        return self._get_views()

    def get_all_generator(self, view_id, limit=None):
        return self._get_all_generator(view_id=view_id, limit=limit)

    def get_all(self, view_id, limit=None):
        return list(self.get_all_generator(view_id=view_id, limit=limit))

    def get(self, id):
        return self._get_by_id(id=id)

    def create(self, data):
        res = self._request_generic(requests.post, path=f'/{self.resource_type}', 
                                    data={self.resource_type_singular: data})
        return res

    def update(self, id, data):
        res = self._request_generic(requests.put, path=f'/{self.resource_type}/{id}', 
                                    data={self.resource_type_singular: data})
        return res

    def delete(self, id):
        res = self._request_generic(requests.delete, path=f'/{self.resource_type}/{id}')
        return res

    def forget(self, id):
        res = self._request_generic(requests.delete, path=f'/{self.resource_type}/{id}/forget')
        return res


class Contacts(APIBase):
    def __init__(self, domain, api_key):
        default_params = {'include': 'sales_accounts,appointments,owner,contact_status',
                          'sort': 'updated_at', 'sort_type': 'desc'}
        super().__init__(domain=domain, api_key=api_key,
                         resource_type='contacts', default_params=default_params)

    def _normalize(self, obj, container):
        users = []
        if 'users' in container:
            users = container['users']
        contact_statuses = []
        if 'contact_status' in container:
            contact_statuses = container['contact_status']
        appointments = []
        if 'appointments' in container:
            appointments = container['appointments']
        outcomes = []
        if 'outcomes' in container:
            outcomes = container['outcomes']

        if 'owner_id' in obj:
            owner = APIBase._find_obj_by_id(objs=users, id=obj['owner_id'])
            obj['owner'] = owner
        if 'contact_status_id' in obj:
            contact_status = APIBase._find_obj_by_id(objs=contact_statuses, id=obj['contact_status_id'])
            obj['contact_status'] = contact_status
        if 'appointment_ids' in obj:
            res = []
            for appointment_id in obj['appointment_ids']:
                ap = APIBase._find_obj_by_id(objs=appointments, id=appointment_id)
                outcome = APIBase._find_obj_by_id(objs=outcomes, id=ap['outcome_id'])
                ap['outcome'] = outcome
                res.append(ap)
            obj['appointments'] = res


    def get_activities(self, id):
        return self._get_generic(f'/contacts/{id}/activities')['activities']

    def get_appointments(self, id):
        return self._get_generic(f'/contacts/{id}/appointments')['appointments']

    def bulk_delete(self, ids):
        return self._request_generic(requests.post, '/contacts/bulk_destroy', 
                                     data={"selected_ids": ids})


class Accounts(APIBase):
    def __init__(self, domain, api_key):
        default_params = {'include': 'appointments,owner,industry_type',
                          'sort': 'updated_at', 'sort_type': 'desc'}
        super().__init__(domain=domain, api_key=api_key,
                         resource_type='sales_accounts', default_params=default_params)

    def _normalize(self, obj, container):
        users = []
        if 'users' in container:
            users = container['users']
        if 'owner_id' in obj:
            owner = APIBase._find_obj_by_id(objs=users, id=obj['owner_id'])
            obj['owner'] = owner
        industry_types = []
        if 'industry_types' in container:
            industry_types = container['industry_types']
        if 'industry_type_id' in obj:
            industry_type = APIBase._find_obj_by_id(objs=industry_types, id=obj['industry_type_id'])
            obj['industry_type'] = industry_type


class Deals(APIBase):
    def __init__(self, domain, api_key):
        default_params = {'include': 'sales_account,appointments,owner,deal_stage',
                          'sort': 'updated_at', 'sort_type': 'desc'}
        super().__init__(domain=domain, api_key=api_key,
                         resource_type='deals', default_params=default_params)

    def _normalize(self, obj, container):
        users = []
        sales_accounts = []
        deal_stages = []
        if 'users' in container:
            users = container['users']
        if 'sales_accounts' in container:
            sales_accounts = container['sales_accounts']
        if 'deal_stages' in container:
            deal_stages = container['deal_stages']
        if 'owner_id' in obj:
            owner = APIBase._find_obj_by_id(objs=users, id=obj['owner_id'])
            obj['owner'] = owner
        if 'sales_account_id' in obj:
            sales_account = APIBase._find_obj_by_id(
                objs=sales_accounts, id=obj['sales_account_id'])
            obj['sales_account'] = sales_account
        if 'deal_stage_id' in obj:
            deal_stage = APIBase._find_obj_by_id(
                objs=deal_stages, id=obj['deal_stage_id'])
            obj['deal_stage'] = deal_stage

class Leads(APIBase):
    def __init__(self, domain, api_key):
        default_params = {'include': 'sales_account,appointments,owner,lead_stage',
                          'sort': 'updated_at', 'sort_type': 'desc'}
        super().__init__(domain=domain, api_key=api_key,
                         resource_type='leads', default_params=default_params)

    def _normalize(self, obj, container):
        users = []
        lead_stage = []
        if 'users' in container:
            users = container['users']
        if 'owner_id' in obj:
            owner = APIBase._find_obj_by_id(objs=users, id=obj['owner_id'])
            obj['owner'] = owner
        if 'lead_stages' in container:
            lead_stages = container['lead_stages']
        if 'lead_stage_id' in obj:
            lead_stage = APIBase._find_obj_by_id(objs=lead_stages, id=obj['lead_stage_id'])
            obj['lead_stage'] = lead_stage

class FreshsalesSDK:
    def __init__(self, domain, api_key):
        self.contacts = Contacts(domain=domain, api_key=api_key)
        self.accounts = Accounts(domain=domain, api_key=api_key)
        self.deals = Deals(domain=domain, api_key=api_key)
        self.leads = Leads(domain=domain, api_key=api_key)
