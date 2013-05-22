import re
import tornado.ioloop
import tornado.web
import tornado.httpclient
import Image
import numpy
from cStringIO import StringIO

def classify_val(val):
    v = val
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val

class MainHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous

    def get(self):
        self.set_header('Content-Type', 'image/png')
	url = self.get_argument("url", "", True)

        if url:
            self.load_images(url, 1)
            try:
                http_client = tornado.httpclient.AsyncHTTPClient()
                http_client.fetch(url, self.handle_request)
            except error:
                print error
                self.finish()
        else:
            print "Gonna need a URL there, bub"
            self.finish()
	#self.write(filter + "\t" + url)
	#self.finish()

    def load_images(self, url, rings):
        self.__results = {}

        prefix, coords, suffix = re.split(r'(\d+/\d+/\d+)', url, 1)
        center_z, center_x, center_y = [int(c) for c in coords.split("/")]

        url_list = []
        for y in range(center_y - rings + 1, center_y + rings):
            for x in range(center_x - rings + 1, center_x + rings):
                temp_url = prefix + '/'.join(str(v) for v in [center_z, x, y]) + suffix
                url_list.append(temp_url)

    def handle_request(self, response):
        if response.error:                                                   
            print("Error:", response.error)
            self.finish()
        else:                                                                
            image = Image.open(StringIO(response.body))
            filter = self.get_argument("filter", "invert", True)
            print "filtering:", filter, self.parse(filter)
            
            inv_im = self.invert(image)
            img_buff = StringIO()
            inv_im.save(img_buff, 'png')
            self.write(img_buff.getvalue())
            self.finish()

    def parse(self, filter_string):
        filter_string = "blur(radius=40,type=gaussian)"
        parts = filter_string.partition("(")
        filter_type = parts[0]
        args = {}
        if parts[2]:
            arg_string = parts[2]
            if arg_string[-1] == ')':
                arg_string = arg_string[:-1]
                arg_split = arg_string.split(",")
                for a in arg_split:
                    key, eq, val = a.partition("=")
                    val = classify_val(val)
                    args[key] = val
            else:
                print("Error: No terminating parenthesis in filter args")
        return filter_type, args

    def invert(self, image):
        arr = 255 - numpy.array(image)
        return Image.fromarray(arr)

application = tornado.web.Application([
    (r"/", MainHandler),
])

if __name__ == "__main__":
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()
