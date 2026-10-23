"""SiliconFlow vision adapter using exactly the project's image review policy."""
import asyncio
import json
import re
import time

import httpx

from image_subject_settings import CLOUD_MODEL, CLOUD_URL


class CloudImageError(ValueError):
    def __init__(self, code, fatal=False):
        super().__init__(code)
        self.fatal = fatal


class SiliconFlowImageReviewer:
    def __init__(self, root, api_key, transport=None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(90, connect=15),
            headers={'Authorization': 'Bearer ' + api_key}, transport=transport)
        self.last_request = 0

    async def start(self):
        if not self.api_key:
            raise CloudImageError('image_subject_key_missing', fatal=True)

    async def classify(self, path):
        from image_subject import encode_image, PROMPT, SCHEMA, MAX_TOKENS, valid_prediction, prediction_consistency_issue, CONSISTENCY_RECHECK
        data, size = await asyncio.to_thread(encode_image, path)
        body = {'model': CLOUD_MODEL, 'temperature': 0, 'max_tokens': MAX_TOKENS, 'enable_thinking': False,
            'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': [
                {'type': 'text', 'text': 'Identify the main subject and image type. Judge only the pixels.'},
                {'type': 'image_url', 'image_url': {'url': data, 'detail': 'high'}}]}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'main_subject_and_type', 'strict': True, 'schema': SCHEMA}}}
        code = 'image_subject_cloud_failed'
        contradictions = []
        for attempt in range(4):
            await asyncio.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            delay = min(2 ** (attempt + 1), 30)
            try:
                response = await self.client.post(CLOUD_URL, json=body)
                if response.status_code in (401, 403):
                    raise CloudImageError('image_subject_key_rejected', fatal=True)
                if response.status_code == 400 and body['response_format']['type'] == 'json_schema':
                    body['response_format'] = {'type': 'json_object'}
                    continue
                if response.status_code == 429:
                    code = 'image_subject_cloud_rate_limit'
                    try:
                        delay = min(max(float(response.headers.get('Retry-After', delay)), delay), 30)
                    except ValueError:
                        pass
                elif response.status_code >= 500:
                    code = 'image_subject_cloud_unavailable'
                elif response.status_code != 200:
                    raise CloudImageError('image_subject_cloud_request_rejected', fatal=True)
                else:
                    raw = response.json()
                    content = raw['choices'][0]['message']['content'].strip()
                    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
                    result = json.loads(content)
                    if not valid_prediction(result):
                        raise ValueError('invalid_prediction')
                    issue = prediction_consistency_issue(result)
                    if issue:
                        contradictions.append({'raw_output': content, 'issue': issue})
                        if len(contradictions) < 2 and attempt < 3:
                            body['messages'][1]['content'][0]['text'] = CONSISTENCY_RECHECK
                            continue
                    return {**result, 'provider': 'siliconflow', 'input_size': size, 'usage': raw.get('usage'),
                        'raw_output': content, 'attempts': attempt + 1,
                        'consistency_status': 'pending' if issue else 'verified', 'consistency_reason': issue,
                        'consistency_rechecks': contradictions,
                        'trace_id': response.headers.get('x-siliconcloud-trace-id')}
            except CloudImageError:
                raise
            except httpx.TimeoutException:
                code = 'image_subject_cloud_timeout'
            except httpx.HTTPError:
                code = 'image_subject_cloud_network'
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                code = 'image_subject_cloud_invalid_response'
            if attempt < 3:
                await asyncio.sleep(delay)
        # Never include provider response text, auth headers or key in an error.
        raise CloudImageError(code)

    async def close(self):
        await self.client.aclose()
