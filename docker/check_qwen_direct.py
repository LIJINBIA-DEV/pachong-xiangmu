"""Live synthetic SiliconFlow call after Jev relay deployment; no saved data changes."""
import asyncio
import json
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw, ImageFont
from image_subject_cloud import SiliconFlowImageReviewer
from image_subject_settings import runtime_settings

async def main():
    options=runtime_settings(Path('/app/data'))
    assert options['provider']=='siliconflow'
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'card.png'
        image=Image.new('RGB',(480,480),'#dfefff')
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',42)
        ImageDraw.Draw(image).multiline_text((25,105),'A HAPPY DAY\n\nENJOY LIFE\n\nBE YOURSELF',font=font,fill='black',spacing=20)
        image.save(path)
        reviewer=SiliconFlowImageReviewer(Path(directory),options['api_key'])
        try:
            result=await reviewer.classify(path)
        finally:
            await reviewer.close()
        print(json.dumps({'provider':result['provider'],'model':options['model'],
            'type':result['image_type'],'jev_relay_used':False},ensure_ascii=False))

if __name__=='__main__':
    asyncio.run(main())
