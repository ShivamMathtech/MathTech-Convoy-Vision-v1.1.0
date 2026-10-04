"""Browser-test server only: retain real ONNX inference and add controlled latency."""
import time
from contextlib import asynccontextmanager
from backend.app import create_app

app=create_app()
original_lifespan=app.router.lifespan_context

@asynccontextmanager
async def slow_lifespan(application):
    async with original_lifespan(application):
        registry=application.state.registry
        model=registry.get('yolov8n-seg')
        original_predict=model.predict
        def delayed_predict(*args,**kwargs):
            time.sleep(.45)
            return original_predict(*args,**kwargs)
        model.predict=delayed_predict
        yield

app.router.lifespan_context=slow_lifespan
