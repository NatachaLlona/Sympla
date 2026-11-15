from django.http import HttpResponse, JsonResponse
from dotenv import load_dotenv
import os
import requests

# Carrega variáveis do .env
load_dotenv()

# Classe ping, usada pelo endpoint ping, para validar conexão com o servidor
def ping(request):
    return HttpResponse("pong", status=200)

# Classe update, usada pelo endpoint update para gerar nova versão do banco de dados
def update(request):
    url = os.getenv('SYMPLA_API_HOST', '').rstrip('/') + '/events'
    token = os.getenv('SYMPLA_API_KEY')
    # Recupera o page_size do .env e converte para inteiro
    page_size_env = os.getenv('SYMPLA_API_PAGE_SIZE')
    # Se a variável não estiver definida ou estiver vazia, usa 200 como padrão
    page_size = int(page_size_env) if page_size_env and page_size_env.isdigit() else 200


    if not token:
        return JsonResponse({
            'status': 'erro',
            'mensagem': 'Token da API não encontrado. Verifique o arquivo .env'
        }, status=500)

    headers = {
        's_token': token
    }

    all_events = []
    page = 1

    try:
        while True:
            params = {
                'page': page,
                'page_size': page_size
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code != 200:
                return JsonResponse({
                    'status': 'erro',
                    'mensagem': f'Erro da API Sympla: código {response.status_code}',
                    'detalhes': response.text,
                    'pagina_solicitada': page
                }, status=response.status_code)

            data = response.json()

            # Adiciona os eventos retornados à lista principal
            eventos = data.get('data', [])
            all_events.extend(eventos)

            # Paginação
            pagination = data.get('pagination', {})
            current_page = pagination.get('page', page)
            total_registros = pagination.get('quantity', 0)
            page_size_resposta = pagination.get('page_size', page_size)

            total_paginas = (total_registros + page_size_resposta - 1) // page_size_resposta

            if current_page >= total_paginas:
                break

            page += 1

        return JsonResponse({
            'status': 'sucesso 2',
            'quantidade_total': len(all_events),
            'eventos': all_events
        })

    except requests.exceptions.Timeout:
        return JsonResponse({
            'status': 'erro',
            'mensagem': 'Tempo limite excedido ao tentar acessar a API Sympla.'
        }, status=504)

    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'status': 'erro',
            'mensagem': 'Não foi possível conectar à API Sympla. Verifique sua conexão ou se a API está online.'
        }, status=503)

    except requests.exceptions.RequestException as e:
        return JsonResponse({
            'status': 'erro',
            'mensagem': 'Erro inesperado ao tentar acessar a API Sympla.',
            'detalhes': str(e)
        }, status=502)
