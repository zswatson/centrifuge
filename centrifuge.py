import re
import tornado.ioloop
import tornado.web
import tornado.httpclient
import Image
import numpy
from numpy import fromstring, ubyte, e, array, add, uint8, copy, clip
from scipy.ndimage.filters import convolve1d
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
            self.load_images(url, 2)
            try:
                http_client = tornado.httpclient.AsyncHTTPClient()
                #http_client.fetch(url, self.handle_request)
            except error:
                print error
                self.finish()
        else:
            print "Gonna need a URL there, bub"
            self.finish()
	#self.write(filter + "\t" + url)
	#self.finish()

    def coords_from_url(self, url):
        prefix, coords, suffix = re.split(r'(\d+/\d+/\d+)', url, 1)
        return prefix, [int(c) for c in coords.split("/")], suffix

    def load_images(self, url, rings):
        self.__rings = rings
        self.__results = {}
        self.__pending = 0

        prefix, coords, suffix = self.coords_from_url(url)
        self.__center_z, self.__center_x, self.__center_y = coords

        url_list = []
        for y in range(self.__center_y - rings + 1, self.__center_y + rings):
            for x in range(self.__center_x - rings + 1, self.__center_x + rings):
                temp_url = prefix + '/'.join(str(v) for v in [self.__center_z, x, y]) + suffix
                url_list.append(temp_url)
                self.__pending += 1
                print "requesting", temp_url
                http_client = tornado.httpclient.AsyncHTTPClient()
                http_client.fetch(temp_url, self.__item_callback)

    def __item_callback(self, response):
        z, x, y = self.coords_from_url(response.request.url)[1]
        offset_x = x - self.__center_x
        offset_y = y - self.__center_y

        print "item_callback", offset_x, offset_y
        self.__results[(offset_x, offset_y)] = response.body
        self.__pending -= 1
        if self.__pending == 0:
            self.__process_results()

    def __process_results(self):
        images = {}
        for key in self.__results:
            images[key] = Image.open(StringIO(self.__results[key]))

        rows = 1 + (self.__rings - 1) * 2
        
        size = images[(0,0)].size
        metatile = Image.new("RGBA", [t * rows for t in size])

        for key in images:
            x = size[0] * (key[0] + self.__rings - 1)
            y = size[1] * (key[1] + self.__rings - 1)
            print "image", key, "pasting at", x, y
            im = images[key]
            metatile.paste(im, (x, y))

        # perform filtering
        metatile = self.gaussian(metatile, 10)

        img_buff = StringIO()
        metatile.save(img_buff, 'png')
        self.write(img_buff.getvalue())
        self.finish()

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

    def gaussian(self, image, radius):
        data = numpy.array(image)        

        kernel = range(-radius, radius + 1)
        kernel = [(d ** 2) / (2 * (radius * .5) ** 2) for d in kernel]
        kernel = [e ** -d for d in kernel]
        kernel = array(kernel, dtype=float) / sum(kernel)

        convolve1d(data, kernel, output=data, axis=0)
        convolve1d(data, kernel, output=data, axis=1)

        return Image.fromarray(data)

    def invert(self, image):
        arr = 255 - numpy.array(image)
        return Image.fromarray(arr)

application = tornado.web.Application([
    (r"/", MainHandler),
])

if __name__ == "__main__":
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()
