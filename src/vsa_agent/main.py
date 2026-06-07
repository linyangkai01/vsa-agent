import uvicorn
from vsa_agent.api.routes import app
from vsa_agent.config import get_config

if __name__ == '__main__':
    cfg = get_config()
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)
