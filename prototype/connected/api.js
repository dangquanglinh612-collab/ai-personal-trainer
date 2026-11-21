const BASE_PATH = '/api/v1';

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function request(path, { method = 'GET', body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (method === 'POST') headers['X-AI-Coach-Request'] = '1';
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(BASE_PATH + path, {
      method, headers, signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查网络后重试。');
  }

  const payload = await response.json().catch(() => null);
  if (response.ok && payload?.success === true && Object.hasOwn(payload, 'data')) {
    return payload.data;
  }
  const code = payload?.error?.code;
  const messages = {
    401: code === 'LOGIN_FAILED' ? '登录失败，请检查邮箱和密码后重试。' : '登录已失效，请重新登录。',
    403: code === 'COACH_NOT_ALLOWED' ? '此账号未获准进入教练工作台。' : '请求被拒绝，请从工作台地址重新打开。',
    404: '未找到该会员或记录。',
    422: '请求参数无效。',
  };
  throw new ApiError(response.status, code, messages[response.status] || '服务暂时无法完成请求，请重试。');
}
