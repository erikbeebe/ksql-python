import functools
import json
import time

import requests
from requests import Timeout

from ksql.builder import SQLBuilder
from ksql.errors import CreateError, InvalidQueryError


class BaseAPI(object):
    def __init__(self, url, **kwargs):
        self.url = url
        self.max_retries = kwargs.get("max_retries", 3)
        self.delay = kwargs.get("delay", 0)
        self.timeout = kwargs.get("timeout", 5)

    def get_timout(self):
        return self.timeout

    @staticmethod
    def _validate_sql_string(sql_string):
        if len(sql_string) > 0:
            if sql_string[-1] != ';':
                sql_string = sql_string + ';'
        else:
            raise InvalidQueryError(sql_string)
        return sql_string

    @staticmethod
    def _parse_ksql_res(r, error):
        if 'commandStatus' in str(r[0]):
            status = r[0]['currentStatus']['commandStatus']['status']
            if status == 'SUCCESS':
                return True
            else:
                raise CreateError(r[0]['currentStatus']['commandStatus']['message'])
        else:
            r = 'Message: ' + r[0]['error']['errorMessage']['message']
            raise CreateError(r)

    def ksql(self, ksql_string, streams_properties={}):
        r = self._request(endpoint='ksql', sql_string=ksql_string, streams_properties=streams_properties)

        if r.status_code == 200:
            r = r.json()
            return r
        else:
            raise ValueError(
                'Status Code: {}.\nMessage: {}'.format(
                    r.status_code, r.content))

    def query(self, query_string, encoding='utf-8', chunk_size=128, streams_properties={}):
        """
        Process streaming incoming data.

        """
        r = self._request(endpoint='query', sql_string=query_string, streams_properties=streams_properties)

        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk != b'\n':
                # this probably needs to change - you need the entire json doc
                # to deserialize it obviously, so the chunk_size has to be at
                # least as large as the largest doc we expect to receive
                # (which right now, the largest docs are usually errors with
                # stack traces in them, not actual valid rows)
                yield json.loads(chunk.decode(encoding))

    def _request(self, endpoint, method='post', sql_string='', streams_properties={}):
        url = '{}/{}'.format(self.url, endpoint)

        sql_string = self._validate_sql_string(sql_string)
        data = json.dumps({
            "ksql": sql_string,
            "streamsProperties": streams_properties
        })

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        if endpoint == 'query':
            stream = True
        else:
            stream = False

        r = requests.request(
            method=method,
            url=url,
            data=data,
            timeout=self.timeout,
            headers=headers,
            stream=stream)

        return r

    @staticmethod
    def retry(exceptions, delay=1, max_retries=5):
        """
        A decorator for retrying a function call with a specified delay in case of a set of exceptions

        Parameter List
        -------------
        :param exceptions:  A tuple of all exceptions that need to be caught for retry
                                            e.g. retry(exception_list = (Timeout, Readtimeout))
        :param delay: Amount of delay (seconds) needed between successive retries.
        :param times: no of times the function should be retried

        """

        def outer_wrapper(function):
            @functools.wraps(function)
            def inner_wrapper(*args, **kwargs):
                final_excep = None
                for counter in range(max_retries):
                    if counter > 0:
                        time.sleep(delay)
                    final_excep = None
                    try:
                        value = function(*args, **kwargs)
                        return value
                    except (exceptions) as e:
                        final_excep = e
                        pass  # or log it

                if final_excep is not None:
                    raise final_excep

            return inner_wrapper

        return outer_wrapper


class SimplifiedAPI(BaseAPI):
    def __init__(self, url, **kwargs):
        super(SimplifiedAPI, self).__init__(url, **kwargs)

    def create_stream(
            self,
            table_name,
            columns_type,
            topic,
            value_format='JSON'):
        return self._create(table_type='stream',
                            table_name=table_name,
                            columns_type=columns_type,
                            topic=topic,
                            value_format=value_format)

    def create_table(self, table_name, columns_type, topic, value_format):
        return self._create(table_type='table',
                            table_name=table_name,
                            columns_type=columns_type,
                            topic=topic,
                            value_format=value_format)

    def create_stream_as(
            self,
            table_name,
            select_columns,
            src_table,
            kafka_topic=None,
            value_format='JSON',
            conditions=[],
            partition_by=None,
            **kwargs):
        return self._create_as(table_type='stream',
                               table_name=table_name,
                               select_columns=select_columns,
                               src_table=src_table,
                               kafka_topic=kafka_topic,
                               value_format=value_format,
                               conditions=conditions,
                               partition_by=partition_by,
                               **kwargs)

    def _create(
            self,
            table_type,
            table_name,
            columns_type,
            topic,
            value_format='JSON'):
        ksql_string = SQLBuilder.build(sql_type='create',
                                       table_type=table_type,
                                       table_name=table_name,
                                       columns_type=columns_type,
                                       topic=topic,
                                       value_format=value_format)
        r = self.ksql(ksql_string)
        return self._parse_ksql_res(r, CreateError)

    @BaseAPI.retry(exceptions=(Timeout, CreateError))
    def _create_as(
            self,
            table_type,
            table_name,
            select_columns,
            src_table,
            kafka_topic=None,
            value_format='JSON',
            conditions=[],
            partition_by=None,
            **kwargs):
        ksql_string = SQLBuilder.build(sql_type='create_as',
                                       table_type=table_type,
                                       table_name=table_name,
                                       select_columns=select_columns,
                                       src_table=src_table,
                                       kafka_topic=kafka_topic,
                                       value_format=value_format,
                                       conditions=conditions,
                                       partition_by=partition_by,
                                       **kwargs)
        r = self.ksql(ksql_string)
        return self._parse_ksql_res(r, CreateError)
