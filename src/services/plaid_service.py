from flask import request, Response, json, Blueprint
from src import bcrypt, db
from datetime import datetime, timedelta, timezone
from src.middlewares import authentication_required
import jwt
import os
import uuid
from flask import *
import plaid
from plaid import ApiException
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.transactions_refresh_request import TransactionsRefreshRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from dotenv import load_dotenv
from datetime import date

load_dotenv()

if os.getenv("PLAID_ENV") == "sandbox":
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={
            'clientId': os.getenv("PLAID_CLIENT_ID"),
            'secret': os.getenv("PLAID_SANDBOX_SECRET"),
        }
    )
else:
    configuration = plaid.Configuration(
        host=plaid.Environment.Production,
        api_key={
            'clientId': os.getenv("PLAID_CLIENT_ID"),
            'secret': os.getenv("PLAID_PRODUCTION_SECRET"),
        }
    )

api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

def get_accounts(access_token):
    accounts_request = AccountsGetRequest(access_token=access_token)
    accounts_response = client.accounts_get(accounts_request)
    return accounts_response


def get_institution_name(institution_id):
    institution_request = InstitutionsGetByIdRequest(institution_id=institution_id, country_codes=[CountryCode('US'),CountryCode('CA')])
    institution_response = client.institutions_get_by_id(institution_request)
    return institution_response['institution']['name']