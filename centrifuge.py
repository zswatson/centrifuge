import tornado.ioloop
import tornado.web
import tornado.httpclient
import Image
import numpy
from cStringIO import StringIO

class MainHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous

    def get(self):
	im = Image.new("RGB", (256, 256))
	img_buff = StringIO()
	im.save(img_buff, 'png')
	#self.set_header('Content-Type', 'image/png')
	#self.write(img_buff.getvalue())
	filter = self.get_argument("filter", "", True)
	url = self.get_argument("url", "", True)

	http_client = tornado.httpclient.AsyncHTTPClient()
	http_client.fetch(url, self.handle_request)
	#self.write(filter + "\t" + url)
	#self.finish()

    def handle_request(self, response):
        if response.error:                                                   
            print("Error:", response.error)                                  
        else:                                                                
            image = Image.open(StringIO(response.body))
            inv_im = self.invert(image)

            img_buff = StringIO()
            inv_im.save(img_buff, 'png')
            self.set_header('Content-Type', 'image/png')
            self.write(img_buff.getvalue())
            self.finish()

    def invert(self, image):
        arr = 255 - numpy.array(image)
        return Image.fromarray(arr)

application = tornado.web.Application([
    (r"/", MainHandler),
])

if __name__ == "__main__":
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()
